"""
pytdms.writer
=============
Streaming TDMS file writer.

Key optimisation (from NI spec §Optimization):
  When the same set of channels with the same types and per-chunk value count is
  written consecutively, only the raw data is appended and the ``next_segment_offset``
  field in the already-written lead-in is updated in place (two cheap seeks).  No
  additional metadata is written until the channel layout changes.

CircuitPython 10.x compatible — no ``asyncio``, no ``typing``, no walrus operator,
no ``pathlib``.
"""

import struct

from pytdms.channel import file_object_path, group_path
from pytdms.constants import (
    LEAD_IN_SIZE,
    TOC_DEFAULT,
    TOC_DEFAULT_INTERLEAVED,
)
from pytdms.encoder import (
    byteswap_scans,
    pack_lead_in,
    pack_no_data_index,
    pack_object_meta,
    pack_raw_index,
    pack_same_index,
    pack_values,
    validate_interleaved_raw,
    validate_raw_bytes,
)

_FMT_U32 = struct.Struct("<I")
_FMT_U64 = struct.Struct("<Q")

# Byte offset of next_segment_offset within the lead-in
_NEXT_SEG_OFFSET_POS = 12  # 4 (tag) + 4 (toc) + 4 (version)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _channel_signature(channel, num_values, extra=None):
    """Return a tuple that uniquely identifies a channel's raw-data layout."""
    return (channel.path, channel.data_type, num_values, extra)


def _is_bytes_like(obj):
    """Return True if *obj* can be used as a read-only buffer (bytes, bytearray,
    memoryview)."""
    return isinstance(obj, (bytes, bytearray, memoryview))


def _build_segment_meta(
    channels_and_counts,
    file_properties,
    written_file_obj,
    written_groups,
    current_sigs,
    current_channels,
):
    """Build TDMS segment metadata bytes.

    Parameters
    ----------
    channels_and_counts : list of ``(Channel, num_values, extra)``
    file_properties     : dict | None
    written_file_obj    : bool  \u2014 has the file object been written in a prior segment?
    written_groups      : set   \u2014 group path strings already emitted
    current_sigs        : list | None
    current_channels    : list | None

    Returns
    -------
    (meta_bytes, new_written_file_obj, new_groups)
        ``new_groups`` is a ``set`` of group paths added this call; the
        caller must add them to ``written_groups``.
    """
    objects = []
    new_written_file_obj = written_file_obj
    new_groups = set()

    if not written_file_obj or file_properties:
        fp = list(file_properties.items()) if file_properties else []
        file_props_triples = [(n, dt, v) for n, (dt, v) in fp]
        objects.append(
            pack_object_meta(file_object_path(), pack_no_data_index(), file_props_triples)
        )
        new_written_file_obj = True

    for ch, _, _ in channels_and_counts:
        gp = group_path(ch.group)
        if gp not in written_groups and gp not in new_groups:
            new_groups.add(gp)
            objects.append(pack_object_meta(gp, pack_no_data_index(), None))

    prev_paths = set()
    prev_types = {}
    if current_channels:
        for ch in current_channels:
            prev_paths.add(ch.path)
            prev_types[ch.path] = ch.data_type

    for ch, num_values, extra in channels_and_counts:
        is_new = ch.path not in prev_paths or prev_types.get(ch.path) != ch.data_type
        if is_new:
            index = pack_raw_index(ch.data_type, num_values, extra)
        else:
            prev_sig = next(
                (s for s in (current_sigs or []) if s[0] == ch.path),
                None,
            )
            if prev_sig is not None and prev_sig[2] == num_values and prev_sig[3] == extra:
                index = pack_same_index()
            else:
                index = pack_raw_index(ch.data_type, num_values, extra)
        prop_triples = [(n, dt, v) for n, (dt, v) in ch.properties.items()]
        objects.append(pack_object_meta(ch.path, index, prop_triples))

    meta = bytearray(_FMT_U32.pack(len(objects)))
    for obj in objects:
        meta += obj
    return bytes(meta), new_written_file_obj, new_groups


# ---------------------------------------------------------------------------
# TdmsWriter
# ---------------------------------------------------------------------------


class TdmsWriter:
    """Stream data to a TDMS file.

    Parameters
    ----------
    file_or_path : str | file-like
        Destination file path (opened in ``"wb+"`` mode) or an already-opened
        binary file that supports ``seek``, ``write``, and ``tell``.

    Examples
    --------
    ::

        ch = Channel("Sensors", "Temperature", DataType.FLOAT32)
        with TdmsWriter("output.tdms") as w:
            w.write_segment([(ch, [23.1, 23.4, 23.2])])
            w.write_segment([(ch, [23.0, 22.9])])
    """

    def __init__(self, file_or_path):
        if _is_bytes_like(file_or_path):
            raise TypeError("file_or_path must be a path string or file object")

        if hasattr(file_or_path, "write"):
            self._file = file_or_path
            self._owns_file = False
        else:
            self._file = open(str(file_or_path), "wb+")  # noqa: SIM115 – must stay open across multiple write_segment calls
            self._owns_file = True

        # Check seek capability (needed for same-segment append optimisation)
        try:
            self._file.seek(0, 1)  # SEEK_CUR
            self._seekable = True
        except (AttributeError, OSError):
            self._seekable = False

        # ---- State --------------------------------------------------------
        # Byte position of the most recently written segment's lead-in tag
        self._seg_start = None
        # Byte position of EOF after the most recently written segment
        self._seg_end = None
        # Raw-data byte count for a single chunk (sum across all channels)
        self._chunk_raw_size = 0
        # Channel layout signature of the current open segment
        # List of (channel_path, data_type, num_values) tuples
        self._current_sigs = None
        # Ordered list of Channel objects in the current segment
        self._current_channels = None
        # Groups and file object that have been written to the file already
        self._written_file_obj = False
        self._written_groups = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_segment(self, channel_data_list, file_properties=None):
        """Write one chunk of data, possibly sharing a segment with previous chunks.

        Parameters
        ----------
        channel_data_list : list of ``(Channel, data)`` pairs
            ``data`` can be:
            - a ``list`` or ``tuple`` of Python scalars → packed by the writer
            - ``bytes``, ``bytearray``, or ``memoryview`` → written directly
              (length must be an exact multiple of the channel's type size)
        file_properties : dict | None
            ``{name: (data_type_int, value)}`` properties attached to the file
            object (written once in the first segment).
        """
        if not channel_data_list:
            return

        # Pack raw data for all channels first (resolves value counts)
        packed = []  # list of (Channel, raw_bytes, num_values, extra)
        for channel, data in channel_data_list:
            if _is_bytes_like(data):
                n = validate_raw_bytes(channel.data_type, data, None)
                raw = bytes(data)
                extra = None
            else:
                raw, n, extra = pack_values(channel.data_type, data)
            packed.append((channel, raw, n, extra))

        # Build signatures for layout-change detection
        new_sigs = [_channel_signature(ch, n, extra) for ch, _, n, extra in packed]

        if self._seekable and self._current_sigs is not None and new_sigs == self._current_sigs:
            # ---- Same layout: append raw data to existing segment -----------
            self._append_chunk(packed)
        else:
            # ---- Layout changed (or first write): start a new segment -------
            self._write_new_segment(packed, file_properties, new_sigs)

    def close(self):
        """Flush and close the file (no-op if file was supplied externally)."""
        if self._owns_file and self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

    # Context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ------------------------------------------------------------------
    # Internal: same-segment append (the performance hot-path)
    # ------------------------------------------------------------------

    def _append_chunk(self, packed):
        """Append contiguous raw data to the current segment and update next_seg_offset."""
        raw_bytes = b"".join(rb for _, rb, _, _ in packed)
        self._append_raw(raw_bytes)

    def _append_raw(self, raw_bytes):
        """Write *raw_bytes* at EOF and update the lead-in next_seg_offset."""
        self._file.seek(0, 2)  # SEEK_END
        self._file.write(raw_bytes)
        self._seg_end = self._file.tell()
        new_offset = self._seg_end - (self._seg_start + LEAD_IN_SIZE)
        self._file.seek(self._seg_start + _NEXT_SEG_OFFSET_POS)
        self._file.write(_FMT_U64.pack(new_offset))
        self._file.flush()

    # ------------------------------------------------------------------
    # Internal: new segment
    # ------------------------------------------------------------------

    def _write_new_segment(self, packed, file_properties, new_sigs):
        """Write a complete new TDMS segment (lead-in + meta + raw data)."""
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
        self._flush_segment(meta, raw_data, TOC_DEFAULT, channels, new_sigs)

    def _flush_segment(self, meta, raw_data, toc, channels, new_sigs):
        """Write lead-in + meta + raw_data as a new segment and update all state."""
        raw_data_offset = len(meta)
        lead_in = pack_lead_in(toc, raw_data_offset + len(raw_data), raw_data_offset)
        self._file.seek(0, 2)  # SEEK_END
        self._seg_start = self._file.tell()
        self._file.write(bytes(lead_in))
        self._file.write(meta)
        self._file.write(raw_data)
        self._seg_end = self._file.tell()
        self._file.flush()
        self._current_sigs = new_sigs
        self._current_channels = channels
        self._chunk_raw_size = len(raw_data)

    # ------------------------------------------------------------------
    # Public: pre-interleaved scan buffer (zero byte-reordering)
    # ------------------------------------------------------------------

    def write_interleaved_segment(self, channels, raw_scans, endian="little", file_properties=None):
        """Write a pre-interleaved scan buffer directly to the file.

        Use this when data already arrives in scan order (e.g. a DMA buffer,
        UART/SPI packet stream, or a mixed-type struct) to avoid any
        byte-reordering overhead.

        The ``kTocInterleavedData`` flag (0x20) is always set on segments
        written by this method.

        Parameters
        ----------
        channels  : list of Channel
            Ordered list matching the scan layout:
            ``[ch0_sample][ch1_sample]...[chN_sample]`` repeated per scan.
        raw_scans : bytes | bytearray | memoryview
            N complete scans.  Length must be a multiple of the total scan size.
        endian : ``"little"`` | ``"big"``
            Byte order of *raw_scans*.  Use ``"big"`` when data arrives from a
            big-endian source (e.g. network packets, some IMU/ADC chips); fields
            are swapped field-by-field before writing.
        file_properties : dict | None
            File-level properties (written only in the first segment).

        Raises
        ------
        ValueError
            If *endian* is not ``"little"`` or ``"big"``, the buffer is not a
            multiple of the scan size, or a channel has an unsupported type.
        """
        if endian not in ("little", "big"):
            raise ValueError(f"endian must be 'little' or 'big', got {endian!r}")
        if not channels:
            return
        num_scans = validate_interleaved_raw(channels, raw_scans)
        raw_bytes = byteswap_scans(channels, raw_scans) if endian == "big" else bytes(raw_scans)
        new_sigs = [_channel_signature(ch, num_scans) for ch in channels]
        if self._seekable and self._current_sigs is not None and new_sigs == self._current_sigs:
            self._append_raw(raw_bytes)
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
            self._flush_segment(meta, raw_bytes, TOC_DEFAULT_INTERLEAVED, channels, new_sigs)
