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

from pytdms.channel import file_object_path, group_path
from pytdms.constants import (
    LEAD_IN_SIZE,
    TOC_DEFAULT,
)
from pytdms.encoder import (
    pack_lead_in,
    pack_no_data_index,
    pack_object_meta,
    pack_raw_index,
    pack_same_index,
    pack_values,
    validate_raw_bytes,
)
from pytdms.writer import (
    _NEXT_SEG_OFFSET_POS,
    _channel_signature,
    _is_bytes_like,
)

_FMT_U32 = struct.Struct("<I")
_FMT_U64 = struct.Struct("<Q")


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

        new_sigs = [_channel_signature(ch, n) for ch, _, n, _ in packed]

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

        # Append at current EOF (tracked explicitly — aiofile.seek has no whence)
        self._afile.seek(self._file_pos)
        await self._afile.write(raw_bytes)
        self._file_pos += len(raw_bytes)
        self._seg_end = self._file_pos

        new_offset = self._seg_end - (self._seg_start + LEAD_IN_SIZE)
        self._afile.seek(self._seg_start + _NEXT_SEG_OFFSET_POS)
        await self._afile.write(_FMT_U64.pack(new_offset))
        # Restore position to EOF for subsequent writes
        self._afile.seek(self._file_pos)

    # ------------------------------------------------------------------
    # Internal: new segment (mirrors TdmsWriter._write_new_segment)
    # ------------------------------------------------------------------

    async def _write_new_segment(self, packed, file_properties, new_sigs):
        channels = [ch for ch, _, _, _ in packed]

        prev_paths = set()
        prev_types = {}
        if self._current_channels:
            for ch in self._current_channels:
                prev_paths.add(ch.path)
                prev_types[ch.path] = ch.data_type

        meta = bytearray()
        objects = []

        if not self._written_file_obj or file_properties:
            fp = list(file_properties.items()) if file_properties else []
            file_props_triples = [(n, dt, v) for n, (dt, v) in fp]
            objects.append(
                pack_object_meta(file_object_path(), pack_no_data_index(), file_props_triples)
            )
            self._written_file_obj = True

        for ch in channels:
            gp = group_path(ch.group)
            if gp not in self._written_groups:
                objects.append(pack_object_meta(gp, pack_no_data_index(), None))
                self._written_groups.add(gp)

        for ch, raw_bytes, num_values, extra in packed:
            is_new = ch.path not in prev_paths or prev_types.get(ch.path) != ch.data_type
            if is_new:
                index = pack_raw_index(ch.data_type, num_values, extra)
            else:
                prev_sig = next(
                    (s for s in (self._current_sigs or []) if s[0] == ch.path),
                    None,
                )
                if prev_sig is not None and prev_sig[2] == num_values:
                    index = pack_same_index()
                else:
                    index = pack_raw_index(ch.data_type, num_values, extra)

            prop_triples = [(n, dt, v) for n, (dt, v) in ch.properties.items()]
            objects.append(pack_object_meta(ch.path, index, prop_triples))

        meta += _FMT_U32.pack(len(objects))
        for obj in objects:
            meta += obj

        raw_data = b"".join(rb for _, rb, _, _ in packed)
        raw_data_offset = len(meta)
        next_seg_offset = raw_data_offset + len(raw_data)

        lead_in = pack_lead_in(TOC_DEFAULT, next_seg_offset, raw_data_offset)

        self._afile.seek(self._file_pos)
        self._seg_start = self._file_pos

        payload = bytes(lead_in) + bytes(meta) + raw_data
        await self._afile.write(payload)
        self._file_pos += len(payload)
        self._seg_end = self._file_pos

        self._current_sigs = new_sigs
        self._current_channels = channels
        self._chunk_raw_size = len(raw_data)
