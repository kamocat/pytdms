"""
tdms.encoder
==============
Pure-function binary serialisation for TDMS segments.

All functions return ``bytes`` or ``bytearray`` objects and perform zero I/O.
This module contains no Python 3.9+ syntax and no standard-library imports
beyond ``struct``, so it is fully compatible with CircuitPython 10.x.
"""

import struct

from tdms.constants import (
    _NO_DATA_INDEX,
    _SAME_INDEX,
    _TYPE_INFO,
    LEAD_IN_SIZE,
    RAW_INDEX_PAYLOAD_FIXED,
    RAW_INDEX_PAYLOAD_STRING,
    TAG,
    VERSION,
    DataType,
)

# ---------------------------------------------------------------------------
# String encoding
# ---------------------------------------------------------------------------


def encode_string(s):
    """Encode a Python string to TDMS wire format: ``u32_len + utf8_bytes``.

    Returns a ``bytearray``.  The length field counts UTF-8 bytes, not characters.
    """
    utf8 = s.encode("utf-8")
    out = bytearray(4 + len(utf8))
    struct.pack_into("<I", out, 0, len(utf8))
    out[4:] = utf8
    return out


# ---------------------------------------------------------------------------
# Value encoding
# ---------------------------------------------------------------------------


def encode_value(data_type, value):
    """Encode a single scalar *value* of *data_type* to ``bytes``.

    Supported types: all entries in ``_TYPE_INFO`` plus special handling for
    STRING (returns ``encode_string``) and TIMESTAMP (expects ``(i64, u64)``
    tuple of NI-epoch seconds + sub-second fractions).

    Raises ``ValueError`` for unsupported types or malformed values.
    """
    if data_type == DataType.STRING:
        return bytes(encode_string(value))

    if data_type == DataType.TIMESTAMP:
        # value must be (i64_seconds_since_ni_epoch, u64_fractions)
        sec, frac = value
        return struct.pack("<qQ", sec, frac)

    if data_type == DataType.BOOLEAN:
        return struct.pack("<B", 1 if value else 0)

    info = _TYPE_INFO.get(data_type)
    if info is None or info[0] is None:
        raise ValueError(f"Unsupported data type: {data_type}")
    fmt_char, _ = info
    return struct.pack("<" + fmt_char, value)


# ---------------------------------------------------------------------------
# Lead-in
# ---------------------------------------------------------------------------


def pack_lead_in(toc, next_seg_offset, raw_data_offset):
    """Build the 28-byte TDMS segment lead-in.

    Parameters
    ----------
    toc:              int  — ToC bitmask (use constants from ``ToC``)
    next_seg_offset:  int  — bytes from end-of-lead-in to end of this segment
    raw_data_offset:  int  — bytes from end-of-lead-in to start of raw data
                             (equals total meta-data length)

    Returns a ``bytearray`` of exactly 28 bytes.
    """
    out = bytearray(LEAD_IN_SIZE)
    out[0:4] = TAG
    struct.pack_into("<IIQQ", out, 4, toc, VERSION, next_seg_offset, raw_data_offset)
    return out


def update_next_seg_offset(buf, offset, new_value):
    """Overwrite the ``next_segment_offset`` field inside an already-written
    lead-in.  ``buf`` can be a writable file that supports ``seek``/``write``,
    or the function is also usable with an in-memory ``bytearray``.

    This is a helper called by ``TdmsWriter`` after data is appended so the
    offset can be fixed in-place without rewriting the whole lead-in.

    ``offset`` is the absolute byte position of the lead-in in the file
    (i.e. the position of the ``TDSm`` tag).
    """
    struct.pack_into("<Q", buf, offset + 12, new_value)


# ---------------------------------------------------------------------------
# Raw-data index
# ---------------------------------------------------------------------------


def pack_no_data_index():
    """Return the 4-byte sentinel meaning "no raw data for this object"."""
    return _NO_DATA_INDEX


def pack_same_index():
    """Return the 4-byte sentinel meaning "raw data index unchanged from
    the previous segment"."""
    return _SAME_INDEX


def pack_raw_index(data_type, num_values, total_string_bytes=None):
    """Build a full raw-data index entry for a channel with new index info.

    For fixed-width types the index is 20 bytes:
        u32 payload_len=12  u32 data_type  u32 dim=1  u64 num_values

    For STRING the index is 28 bytes:
        u32 payload_len=20  u32 data_type  u32 dim=1  u64 num_values  u64 total_bytes

    ``total_string_bytes`` must be provided for STRING channels.
    """
    if data_type == DataType.STRING:
        if total_string_bytes is None:
            raise ValueError("total_string_bytes required for STRING channels")
        return struct.pack(
            "<IIIQQ",
            RAW_INDEX_PAYLOAD_STRING,  # payload length (20)
            data_type,
            1,  # array dimension (always 1)
            num_values,
            total_string_bytes,
        )
    return struct.pack(
        "<IIIQ",
        RAW_INDEX_PAYLOAD_FIXED,  # payload length (12)
        data_type,
        1,
        num_values,
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def pack_property(name, data_type, value):
    """Encode a single TDMS property.

    Wire format:  [encoded_name][u32 data_type][encoded_value]

    Returns ``bytes``.
    """
    name_bytes = encode_string(name)
    type_bytes = struct.pack("<I", data_type)
    value_bytes = encode_value(data_type, value)
    return bytes(name_bytes) + type_bytes + value_bytes


# ---------------------------------------------------------------------------
# Meta-data object block
# ---------------------------------------------------------------------------


def pack_object_meta(path, raw_index_bytes, properties):
    """Encode a single TDMS object's meta-data block.

    Parameters
    ----------
    path:             str  — TDMS object path, e.g. ``"/'group'/'channel'"``
    raw_index_bytes:  bytes — one of: pack_raw_index(), pack_no_data_index(),
                              pack_same_index()
    properties:       iterable of ``(name_str, data_type_int, value)`` triples,
                      or ``None``/empty for no properties.

    Returns ``bytearray``.
    """
    path_bytes = encode_string(path)
    prop_list = list(properties) if properties else []

    # Encode properties first so we know the count
    encoded_props = bytearray()
    for prop_name, prop_type, prop_val in prop_list:
        encoded_props += pack_property(prop_name, prop_type, prop_val)

    out = bytearray()
    out += path_bytes
    out += raw_index_bytes
    out += struct.pack("<I", len(prop_list))
    out += encoded_props
    return out


# ---------------------------------------------------------------------------
# Interleaved raw-data layout
# ---------------------------------------------------------------------------


def scan_size(channels):
    """Return the total byte width of one complete scan across *channels*.

    Raises ``ValueError`` if any channel has an unsupported or variable-width
    type (STRING).
    """
    total = 0
    for ch in channels:
        info = _TYPE_INFO.get(ch.data_type)
        if info is None:
            raise ValueError(f"Unsupported data type: {ch.data_type}")
        if info[1] is None:
            raise ValueError(
                f"Channel '{ch.path}' has variable-width type (STRING); "
                "cannot be used in interleaved mode"
            )
        total += info[1]
    return total


def validate_interleaved_raw(channels, raw_scans):
    """Validate a pre-interleaved buffer against *channels* and return num_scans.

    Parameters
    ----------
    channels  : ordered list of Channel objects matching the scan layout
    raw_scans : bytes | bytearray | memoryview

    Returns
    -------
    int \u2014 number of complete scans contained in *raw_scans*

    Raises
    ------
    ValueError
        If the buffer length is not a multiple of the scan size, or a channel
        has an unsupported type.
    """
    ss = scan_size(channels)
    n = len(raw_scans)
    if n % ss != 0:
        raise ValueError(f"Buffer length {n} is not a multiple of scan size {ss}")
    return n // ss


def byteswap_scans(channels, raw_scans):
    """Convert a big-endian pre-interleaved scan buffer to little-endian.

    For each scan, reverses the bytes of every field according to its channel's
    type size.  TIMESTAMP samples (16 bytes) are treated as two independent
    8-byte fields (seconds + fractions).  Single-byte fields are unchanged.

    Parameters
    ----------
    channels  : ordered list of Channel objects
    raw_scans : bytes | bytearray | memoryview  (big-endian source)

    Returns
    -------
    bytes  \u2014 same data with each sample's bytes reversed to little-endian

    Raises
    ------
    ValueError
        If any channel has an unsupported or variable-width type.
    """
    # Pre-compute field swap sizes within one scan
    # TIMESTAMP (16 bytes) is swapped as two 8-byte halves.
    swap_sizes = []
    for ch in channels:
        info = _TYPE_INFO.get(ch.data_type)
        if info is None:
            raise ValueError(f"Unsupported data type: {ch.data_type}")
        if info[1] is None:
            raise ValueError(
                f"Channel '{ch.path}' has variable-width type (STRING); cannot byteswap"
            )
        if ch.data_type == DataType.TIMESTAMP:
            swap_sizes.append(8)  # swap each 8-byte half independently
        else:
            swap_sizes.append(info[1])

    field_widths = [_TYPE_INFO[ch.data_type][1] for ch in channels]
    ss = sum(field_widths)
    buf = bytearray(raw_scans)
    n_scans = len(buf) // ss

    for scan_i in range(n_scans):
        pos = scan_i * ss
        for j in range(len(channels)):
            fwidth = field_widths[j]
            ssize = swap_sizes[j]
            # A field may contain multiple independently-swapped words
            # (currently only TIMESTAMP: fwidth=16, ssize=8 → 2 words)
            words = fwidth // ssize
            for w in range(words):
                start = pos + w * ssize
                end = start + ssize
                # Reverse bytes in-place (CircuitPython-safe: no [::-1] assign)
                lo, hi = start, end - 1
                while lo < hi:
                    buf[lo], buf[hi] = buf[hi], buf[lo]
                    lo += 1
                    hi -= 1
            pos += fwidth

    return bytes(buf)


# ---------------------------------------------------------------------------
# Raw-data packing for Python value sequences
# ---------------------------------------------------------------------------


def pack_values(data_type, values):
    """Pack an iterable of Python scalars into a ``bytes`` object.

    For STRING channels the wire format is:
        [u32 offset_0][u32 offset_1]…[u32 offset_n-1] [utf8_0][utf8_1]…

    where each offset is the byte position of the *start* of that string in
    the concatenated UTF-8 blob.  The last offset therefore equals
    ``total_string_bytes``.

    For all other types: ``struct.pack('<' + fmt * n, *values)``.

    Returns ``(packed_bytes, num_values, extra_info)`` where ``extra_info``
    is ``total_string_bytes`` for STRING, else ``None``.
    """
    values = list(values)  # materialise once (generators not safe to re-iterate)
    n = len(values)

    if data_type == DataType.STRING:
        encoded = [v.encode("utf-8") for v in values]
        offsets = bytearray(4 * n)
        cumulative = 0
        for i, s in enumerate(encoded):
            cumulative += len(s)
            # nptdms (and LabVIEW) expect END offsets: the cumulative byte
            # position of the END of each string within the string-data blob.
            struct.pack_into("<I", offsets, i * 4, cumulative)
        payload = b"".join(encoded)
        # total_size_in_bytes = offset array (4 * n bytes) + all string bytes
        total_raw_bytes = 4 * n + cumulative
        return bytes(offsets) + payload, n, total_raw_bytes

    if data_type == DataType.TIMESTAMP:
        out = bytearray(16 * n)
        for i, (sec, frac) in enumerate(values):
            struct.pack_into("<qQ", out, i * 16, sec, frac)
        return bytes(out), n, None

    if data_type == DataType.BOOLEAN:
        out = bytearray(n)
        for i, v in enumerate(values):
            out[i] = 1 if v else 0
        return bytes(out), n, None

    info = _TYPE_INFO.get(data_type)
    if info is None or info[0] is None:
        raise ValueError(f"Unsupported data type for pack_values: {data_type}")
    fmt_char, byte_size = info
    fmt = "<" + fmt_char * n
    return struct.pack(fmt, *values), n, None


def validate_raw_bytes(data_type, raw_bytes, expected_values):
    """Validate that a bytes-like object has the correct length for
    *expected_values* values of *data_type*.

    Raises ``ValueError`` if the size does not match.
    Returns the number of values (same as *expected_values* for fixed-width,
    or raises for STRING since byte-level raw input for strings is unsupported).
    """
    if data_type == DataType.STRING:
        raise ValueError(
            "Pre-packed bytes input is not supported for STRING channels. "
            "Pass a list of str values instead."
        )
    info = _TYPE_INFO.get(data_type)
    if info is None:
        raise ValueError(f"Unsupported data type: {data_type}")
    _, byte_size = info
    if byte_size is None:
        raise ValueError(f"Cannot validate variable-length type: {data_type}")
    total = len(raw_bytes)
    if total % byte_size != 0:
        raise ValueError(f"Raw bytes length {total} is not a multiple of type size {byte_size}")
    n = total // byte_size
    if expected_values is not None and n != expected_values:
        raise ValueError(
            "Expected %d values (%d bytes) but got %d bytes"
            % (expected_values, expected_values * byte_size, total)
        )
    return n
