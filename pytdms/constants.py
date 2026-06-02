import struct

# ---------------------------------------------------------------------------
# TDMS file tag & version
# ---------------------------------------------------------------------------
TAG = b"TDSm"
TAG_INDEX = b"TDSh"  # same layout but no raw data — index sidecar file
VERSION = 4713        # TDMS 2.0
LEAD_IN_SIZE = 28     # bytes: 4 tag + 4 toc + 4 version + 8 next_seg_offset + 8 raw_data_offset

# Sentinel stored when next_seg_offset is unknown (e.g. mid-write crash)
OFFSET_UNKNOWN = 0xFFFFFFFFFFFFFFFF

# ---------------------------------------------------------------------------
# Table of Contents (ToC) bitmask flags
# ---------------------------------------------------------------------------
class ToC:
    META         = 1 << 1   # 0x02 — segment contains meta data
    NEW_OBJ_LIST = 1 << 2   # 0x04 — segment contains a new object list
    RAW          = 1 << 3   # 0x08 — segment contains raw data
    INTERLEAVED  = 1 << 5   # 0x20 — raw data is interleaved (not used by this writer)
    BIG_ENDIAN   = 1 << 6   # 0x40 — all numerics are big-endian  (not used by this writer)

# Default ToC value for a segment with new object list + meta + raw data (little-endian)
TOC_DEFAULT      = ToC.META | ToC.NEW_OBJ_LIST | ToC.RAW   # 0x0E
# ToC for a segment whose meta hasn't changed — still has raw, still has meta for index info
TOC_CONTINUATION = ToC.META | ToC.RAW                       # 0x0A  (no NEW_OBJ_LIST)

# ---------------------------------------------------------------------------
# Data type identifiers  (tdsDataType enum)
# ---------------------------------------------------------------------------
class DataType:
    VOID      = 0
    I8        = 1
    I16       = 2
    I32       = 3
    I64       = 4
    U8        = 5
    U16       = 6
    U32       = 7
    U64       = 8
    FLOAT32   = 9
    FLOAT64   = 10
    # Extended float (12) intentionally omitted — not supported by nptdms either
    STRING    = 0x20   # 32  — variable-length UTF-8, prefixed by u32 length
    BOOLEAN   = 0x21   # 33  — stored as 1 byte (0 or 1)
    TIMESTAMP = 0x44   # 68  — i64 seconds since 1904-01-01 UTC + u64 (2^-64 s fractions)

# ---------------------------------------------------------------------------
# Per-type information used by encoder & writer
# Each entry: (struct_format_char, byte_size)
# STRING and TIMESTAMP are variable / composite — handled separately in encoder.
# ---------------------------------------------------------------------------
_TYPE_INFO = {
    DataType.I8:      ("b", 1),
    DataType.I16:     ("h", 2),
    DataType.I32:     ("i", 4),
    DataType.I64:     ("q", 8),
    DataType.U8:      ("B", 1),
    DataType.U16:     ("H", 2),
    DataType.U32:     ("I", 4),
    DataType.U64:     ("Q", 8),
    DataType.FLOAT32: ("f", 4),
    DataType.FLOAT64: ("d", 8),
    DataType.BOOLEAN: ("B", 1),   # stored as unsigned byte 0/1
    DataType.TIMESTAMP: (None, 16),  # packed as <qQ (i64 + u64)
    DataType.STRING:    (None, None), # variable length
}

# Types that carry raw data in a channel (excludes VOID)
_RAW_DATA_TYPES = frozenset(_TYPE_INFO.keys()) - {DataType.VOID}

# Types valid as property values
_PROPERTY_TYPES = frozenset(_TYPE_INFO.keys()) | {DataType.VOID}

# ---------------------------------------------------------------------------
# Timestamp epoch helpers
# ---------------------------------------------------------------------------
# NI epoch: 1904-01-01 00:00:00 UTC
# Python epoch: 1970-01-01 00:00:00 UTC
# Offset in seconds between them:
_NI_EPOCH_OFFSET_SECONDS = 2082844800   # (66 years including leap years)

def timestamp_from_datetime(dt):
    """Convert a datetime (assumed UTC) to (i64_seconds, u64_fractions) NI tuple.

    ``dt`` must have a ``timestamp()`` method (datetime.datetime).
    Fractions are always 0 — sub-second precision requires manual construction.
    CircuitPython-safe: no ``datetime`` import here; caller must supply the value.
    """
    unix_seconds = int(dt.timestamp())
    ni_seconds = unix_seconds + _NI_EPOCH_OFFSET_SECONDS
    return (ni_seconds, 0)

# ---------------------------------------------------------------------------
# Raw data index layout sizes
# ---------------------------------------------------------------------------
# Full raw data index for numeric / boolean types:
#   4 (index_len) + 4 (data_type) + 4 (dim=1) + 8 (num_values) = 20 bytes payload
#   index_len field itself stores 12 = 4+4+8 (excludes the index_len u32 itself)
RAW_INDEX_LEN_FIXED = 20   # bytes written to disk for numeric full index
RAW_INDEX_PAYLOAD_FIXED = 12  # value stored inside the index_len field

# Full raw data index for STRING type:
#   same as fixed + 8 (total_bytes) = 28 bytes on disk, index_len field = 20
RAW_INDEX_LEN_STRING = 28
RAW_INDEX_PAYLOAD_STRING = 20

# Pre-packed sentinels (no allocation at runtime)
_NO_DATA_INDEX = struct.pack("<I", 0xFFFFFFFF)
_SAME_INDEX    = struct.pack("<I", 0x00000000)
