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

from pytdms.constants import (
    LEAD_IN_SIZE,
    ToC, TOC_DEFAULT, TOC_CONTINUATION,
    DataType, _TYPE_INFO,
)
from pytdms.encoder import (
    encode_string,
    pack_lead_in,
    pack_raw_index,
    pack_no_data_index,
    pack_same_index,
    pack_object_meta,
    pack_property,
    pack_values,
    validate_raw_bytes,
)
from pytdms.channel import file_object_path, group_path

_FMT_U32 = struct.Struct("<I")
_FMT_U64 = struct.Struct("<Q")

# Byte offset of next_segment_offset within the lead-in
_NEXT_SEG_OFFSET_POS = 12   # 4 (tag) + 4 (toc) + 4 (version)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _channel_signature(channel, num_values):
    """Return a tuple that uniquely identifies a channel's raw-data layout."""
    return (channel.path, channel.data_type, num_values)


def _is_bytes_like(obj):
    """Return True if *obj* can be used as a read-only buffer (bytes, bytearray,
    memoryview)."""
    return isinstance(obj, (bytes, bytearray, memoryview))


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
            self._file = open(str(file_or_path), "wb+")
            self._owns_file = True

        # Check seek capability (needed for same-segment append optimisation)
        try:
            self._file.seek(0, 1)   # SEEK_CUR
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
        packed = []         # list of (Channel, raw_bytes, num_values, extra)
        for channel, data in channel_data_list:
            if _is_bytes_like(data):
                n = validate_raw_bytes(channel.data_type, data, None)
                raw = bytes(data)
                extra = None
            else:
                raw, n, extra = pack_values(channel.data_type, data)
            packed.append((channel, raw, n, extra))

        # Build signatures for layout-change detection
        new_sigs = [_channel_signature(ch, n) for ch, _, n, _ in packed]

        if (
            self._seekable
            and self._current_sigs is not None
            and new_sigs == self._current_sigs
        ):
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
        """Append raw data to the current segment and update next_seg_offset."""
        raw_bytes = b"".join(rb for _, rb, _, _ in packed)

        # Move to end of file and append
        self._file.seek(0, 2)   # SEEK_END
        self._file.write(raw_bytes)
        self._seg_end = self._file.tell()

        # Fix next_segment_offset in the lead-in
        # next_seg_offset = file_size_from_end_of_lead_in = seg_end - (seg_start + LEAD_IN_SIZE)
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

        # Determine which channels are brand-new (need full raw index),
        # which are unchanged (use same-index sentinel),
        # and which groups / file objects need to be emitted.
        prev_paths = set()
        prev_types = {}
        if self._current_channels:
            for ch in self._current_channels:
                prev_paths.add(ch.path)
                prev_types[ch.path] = ch.data_type

        # Detect if the channel set / order changed
        channel_order_changed = (
            self._current_channels is None or
            [ch.path for ch in channels] != [ch.path for ch in self._current_channels]
        )

        # ---- Build meta data bytes ----------------------------------------
        meta = bytearray()
        objects = []    # accumulate object descriptions

        # File object (only the first segment ever, or if file_properties given)
        if not self._written_file_obj or file_properties:
            fp = list(file_properties.items()) if file_properties else []
            file_props_triples = [
                (n, dt, v) for n, (dt, v) in fp
            ]
            objects.append(
                pack_object_meta(
                    file_object_path(),
                    pack_no_data_index(),
                    file_props_triples,
                )
            )
            self._written_file_obj = True

        # Group objects (one per unique group, once)
        new_groups_this_seg = []
        for ch in channels:
            gp = group_path(ch.group)
            if gp not in self._written_groups:
                new_groups_this_seg.append(gp)
                self._written_groups.add(gp)

        for gp in new_groups_this_seg:
            objects.append(
                pack_object_meta(gp, pack_no_data_index(), None)
            )

        # Channel objects
        for ch, raw_bytes, num_values, extra in packed:
            is_new = (ch.path not in prev_paths or prev_types.get(ch.path) != ch.data_type)
            if is_new:
                index = pack_raw_index(ch.data_type, num_values, extra)
            else:
                # Data type matches but count may differ — still emit full index
                # if count changed, otherwise use same-index sentinel
                prev_sig = next(
                    (s for s in (self._current_sigs or []) if s[0] == ch.path),
                    None,
                )
                if prev_sig is not None and prev_sig[2] == num_values:
                    index = pack_same_index()
                else:
                    index = pack_raw_index(ch.data_type, num_values, extra)

            # Channel properties
            prop_triples = [
                (n, dt, v) for n, (dt, v) in ch.properties.items()
            ]
            objects.append(
                pack_object_meta(ch.path, index, prop_triples)
            )

        # Prefix the object list with the object count
        meta += _FMT_U32.pack(len(objects))
        for obj in objects:
            meta += obj

        # ---- Assemble raw data -------------------------------------------
        raw_data = b"".join(rb for _, rb, _, _ in packed)

        # ---- Compute offsets and write the segment -----------------------
        raw_data_offset = len(meta)   # bytes from end-of-lead-in to raw data
        next_seg_offset = raw_data_offset + len(raw_data)

        # ToC: set kTocNewObjList when object list changed
        if channel_order_changed or new_groups_this_seg or not self._written_file_obj:
            toc = TOC_DEFAULT   # META | NEW_OBJ_LIST | RAW
        else:
            toc = TOC_CONTINUATION  # META | RAW

        # Always include NEW_OBJ_LIST on first write or after layout change
        toc = TOC_DEFAULT  # simplest: always emit new obj list — valid per spec

        lead_in = pack_lead_in(toc, next_seg_offset, raw_data_offset)

        # Seek to end and remember segment start
        self._file.seek(0, 2)   # SEEK_END
        self._seg_start = self._file.tell()

        self._file.write(bytes(lead_in))
        self._file.write(bytes(meta))
        self._file.write(raw_data)
        self._seg_end = self._file.tell()
        self._file.flush()

        # Update state
        self._current_sigs = new_sigs
        self._current_channels = channels
        self._chunk_raw_size = len(raw_data)
