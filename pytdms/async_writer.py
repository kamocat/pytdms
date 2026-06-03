"""
pytdms.async_writer
===================
Asynchronous TDMS writer backed by ``aiofile``.

This module is **CPython-only** (requires Python 3.8+ and the ``aiofile``
package).  It is not importable on CircuitPython.  All encoding logic is
delegated to the same :mod:`pytdms.encoder` functions used by the sync writer —
no serialisation code is duplicated here.

Install the optional dependency with::

    pip install "pytdms[async]"
"""

import struct

try:
    import aiofile as _aiofile
except ImportError as _err:
    raise ImportError(
        "AsyncTdmsWriter requires 'aiofile'. " 'Install it with: pip install "pytdms[async]"'
    ) from _err

from pytdms.constants import (
    LEAD_IN_SIZE,
    TOC_DEFAULT,
    TOC_DEFAULT_INTERLEAVED,
)
from pytdms.encoder import (
    byteswap_scans,
    pack_lead_in,
    pack_values,
    validate_interleaved_raw,
    validate_raw_bytes,
)
from pytdms.writer import (
    _NEXT_SEG_OFFSET_POS,
    _build_segment_meta,
    _channel_signature,
    _is_bytes_like,
)


class AsyncTdmsWriter:
    """Asynchronous streaming TDMS writer using ``aiofile``.

    Parameters
    ----------
    path : str
        Destination file path.

    Examples
    --------
    ::

        async with AsyncTdmsWriter("output.tdms") as w:
            await w.write_segment([(ch, [1.0, 2.0, 3.0])])
            await w.write_segment([(ch, [4.0, 5.0])])
    """

    def __init__(self, path):
        self._path = str(path)
        self._afile = None

        # Mirrors TdmsWriter state
        self._seg_start = None
        self._seg_end = None
        self._chunk_raw_size = 0
        self._current_sigs = None
        self._current_channels = None
        self._written_file_obj = False
        self._written_groups = set()
        # Explicit file-position tracking (aiofile.seek has no whence arg)
        self._file_pos = 0

    async def _open(self):
        self._afile = await _aiofile.async_open(self._path, "wb+")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self._open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write_segment(self, channel_data_list, file_properties=None):
        """Async version of :meth:`TdmsWriter.write_segment`."""
        if not channel_data_list:
            return

        packed = []
        for channel, data in channel_data_list:
            if _is_bytes_like(data):
                n = validate_raw_bytes(channel.data_type, data, None)
                raw = bytes(data)
                extra = None
            else:
                raw, n, extra = pack_values(channel.data_type, data)
            packed.append((channel, raw, n, extra))

        new_sigs = [_channel_signature(ch, n, extra) for ch, _, n, extra in packed]

        if self._current_sigs is not None and new_sigs == self._current_sigs:
            await self._append_chunk(packed)
        else:
            await self._write_new_segment(packed, file_properties, new_sigs)

    async def close(self):
        """Flush and close the underlying file."""
        if self._afile is not None:
            await self._afile.flush()
            await self._afile.close()
            self._afile = None

    # ------------------------------------------------------------------
    # Internal: same-segment append
    # ------------------------------------------------------------------

    async def _append_chunk(self, packed):
        raw_bytes = b"".join(rb for _, rb, _, _ in packed)
        await self._append_raw(raw_bytes)

    async def _append_raw(self, raw_bytes):
        """Write *raw_bytes* at current EOF and update the lead-in next_seg_offset."""
        self._afile.seek(self._file_pos)
        await self._afile.write(raw_bytes)
        self._file_pos += len(raw_bytes)
        self._seg_end = self._file_pos
        new_offset = self._seg_end - (self._seg_start + LEAD_IN_SIZE)
        self._afile.seek(self._seg_start + _NEXT_SEG_OFFSET_POS)
        await self._afile.write(struct.pack("<Q", new_offset))
        self._afile.seek(self._file_pos)

    # ------------------------------------------------------------------
    # Internal: new segment (mirrors TdmsWriter._write_new_segment)
    # ------------------------------------------------------------------

    async def _write_new_segment(self, packed, file_properties, new_sigs):
        channels = [ch for ch, _, _, _ in packed]
        channels_and_counts = [(ch, n, extra) for ch, _, n, extra in packed]
        meta, new_wfo, new_groups = _build_segment_meta(
            channels_and_counts,
            file_properties,
            self._written_file_obj,
            self._written_groups,
            self._current_sigs,
            self._current_channels,
        )
        self._written_file_obj = new_wfo
        self._written_groups.update(new_groups)
        raw_data = b"".join(rb for _, rb, _, _ in packed)
        await self._flush_segment(meta, raw_data, TOC_DEFAULT, channels, new_sigs)

    async def _flush_segment(self, meta, raw_data, toc, channels, new_sigs):
        """Write lead-in + meta + raw_data as a new segment and update all state."""
        raw_data_offset = len(meta)
        lead_in = pack_lead_in(toc, raw_data_offset + len(raw_data), raw_data_offset)
        payload = bytes(lead_in) + meta + raw_data
        self._afile.seek(self._file_pos)
        self._seg_start = self._file_pos
        await self._afile.write(payload)
        self._file_pos += len(payload)
        self._seg_end = self._file_pos
        self._current_sigs = new_sigs
        self._current_channels = channels
        self._chunk_raw_size = len(raw_data)

    # ------------------------------------------------------------------
    # Public: pre-interleaved scan buffer
    # ------------------------------------------------------------------

    async def write_interleaved_segment(
        self, channels, raw_scans, endian="little", file_properties=None
    ):
        """Async version of :meth:`TdmsWriter.write_interleaved_segment`."""
        if endian not in ("little", "big"):
            raise ValueError(f"endian must be 'little' or 'big', got {endian!r}")
        if not channels:
            return
        num_scans = validate_interleaved_raw(channels, raw_scans)
        raw_bytes = byteswap_scans(channels, raw_scans) if endian == "big" else bytes(raw_scans)
        new_sigs = [_channel_signature(ch, num_scans) for ch in channels]
        if self._current_sigs is not None and new_sigs == self._current_sigs:
            await self._append_raw(raw_bytes)
        else:
            channels_and_counts = [(ch, num_scans, None) for ch in channels]
            meta, new_wfo, new_groups = _build_segment_meta(
                channels_and_counts,
                file_properties,
                self._written_file_obj,
                self._written_groups,
                self._current_sigs,
                self._current_channels,
            )
            self._written_file_obj = new_wfo
            self._written_groups.update(new_groups)
            await self._flush_segment(meta, raw_bytes, TOC_DEFAULT_INTERLEAVED, channels, new_sigs)
