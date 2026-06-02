"""
Unit tests for pytdms.encoder — pure binary serialisation functions.

These tests have no I/O and do not require nptdms.
"""

import struct
import pytest

from pytdms.constants import DataType, LEAD_IN_SIZE, TAG, VERSION
from pytdms.encoder import (
    encode_string,
    encode_value,
    pack_lead_in,
    pack_raw_index,
    pack_no_data_index,
    pack_same_index,
    pack_property,
    pack_object_meta,
    pack_values,
    validate_raw_bytes,
)


# ---------------------------------------------------------------------------
# encode_string
# ---------------------------------------------------------------------------

class TestEncodeString:
    def test_ascii(self):
        result = encode_string("hello")
        assert result[:4] == struct.pack("<I", 5)
        assert result[4:] == b"hello"

    def test_empty(self):
        result = encode_string("")
        assert len(result) == 4
        assert result == bytearray(4)   # length=0, no payload

    def test_utf8_multibyte(self):
        # "café" — 'é' is 2 bytes in UTF-8
        result = encode_string("café")
        utf8 = "café".encode("utf-8")
        assert result[:4] == struct.pack("<I", len(utf8))
        assert result[4:] == utf8

    def test_path_with_single_quote(self):
        result = encode_string("it's")
        utf8 = "it's".encode("utf-8")
        assert result[4:] == utf8

    def test_returns_bytearray(self):
        assert isinstance(encode_string("x"), bytearray)

    def test_total_length(self):
        s = "abcde"
        result = encode_string(s)
        assert len(result) == 4 + len(s)


# ---------------------------------------------------------------------------
# encode_value
# ---------------------------------------------------------------------------

class TestEncodeValue:
    def test_i8(self):
        assert encode_value(DataType.I8, -1) == struct.pack("<b", -1)

    def test_i16(self):
        assert encode_value(DataType.I16, 1000) == struct.pack("<h", 1000)

    def test_i32(self):
        assert encode_value(DataType.I32, -100000) == struct.pack("<i", -100000)

    def test_i64(self):
        assert encode_value(DataType.I64, 2**40) == struct.pack("<q", 2**40)

    def test_u8(self):
        assert encode_value(DataType.U8, 255) == struct.pack("<B", 255)

    def test_u16(self):
        assert encode_value(DataType.U16, 65535) == struct.pack("<H", 65535)

    def test_u32(self):
        assert encode_value(DataType.U32, 0xDEADBEEF) == struct.pack("<I", 0xDEADBEEF)

    def test_u64(self):
        assert encode_value(DataType.U64, 2**63) == struct.pack("<Q", 2**63)

    def test_float32(self):
        assert encode_value(DataType.FLOAT32, 1.5) == struct.pack("<f", 1.5)

    def test_float64(self):
        assert encode_value(DataType.FLOAT64, 3.14159) == struct.pack("<d", 3.14159)

    def test_boolean_true(self):
        assert encode_value(DataType.BOOLEAN, True) == b"\x01"

    def test_boolean_false(self):
        assert encode_value(DataType.BOOLEAN, False) == b"\x00"

    def test_boolean_truthy_int(self):
        assert encode_value(DataType.BOOLEAN, 42) == b"\x01"

    def test_string(self):
        result = encode_value(DataType.STRING, "hi")
        assert result == bytes(encode_string("hi"))

    def test_timestamp(self):
        result = encode_value(DataType.TIMESTAMP, (100, 200))
        assert result == struct.pack("<qQ", 100, 200)

    def test_unsupported_raises(self):
        with pytest.raises(ValueError):
            encode_value(99, 0)


# ---------------------------------------------------------------------------
# pack_lead_in
# ---------------------------------------------------------------------------

class TestPackLeadIn:
    def test_size(self):
        li = pack_lead_in(0x0E, 100, 50)
        assert len(li) == LEAD_IN_SIZE  # 28

    def test_tag(self):
        li = pack_lead_in(0x0E, 100, 50)
        assert li[:4] == TAG

    def test_version(self):
        li = pack_lead_in(0x0E, 100, 50)
        ver = struct.unpack("<I", li[8:12])[0]
        assert ver == VERSION  # 4713

    def test_toc(self):
        li = pack_lead_in(0x0E, 0, 0)
        toc = struct.unpack("<I", li[4:8])[0]
        assert toc == 0x0E

    def test_next_seg_offset(self):
        li = pack_lead_in(0, 9999, 0)
        val = struct.unpack("<Q", li[12:20])[0]
        assert val == 9999

    def test_raw_data_offset(self):
        li = pack_lead_in(0, 0, 5432)
        val = struct.unpack("<Q", li[20:28])[0]
        assert val == 5432

    def test_returns_bytearray(self):
        assert isinstance(pack_lead_in(0, 0, 0), bytearray)


# ---------------------------------------------------------------------------
# pack_raw_index
# ---------------------------------------------------------------------------

class TestPackRawIndex:
    def test_fixed_size(self):
        # u32 payload_len + u32 dtype + u32 dim + u64 num_values = 20 bytes
        result = pack_raw_index(DataType.FLOAT64, 100)
        assert len(result) == 20

    def test_fixed_payload_len(self):
        result = pack_raw_index(DataType.I32, 50)
        payload_len = struct.unpack("<I", result[:4])[0]
        assert payload_len == 12   # 4+4+8

    def test_fixed_data_type(self):
        result = pack_raw_index(DataType.FLOAT32, 10)
        dtype = struct.unpack("<I", result[4:8])[0]
        assert dtype == DataType.FLOAT32

    def test_fixed_dimension(self):
        result = pack_raw_index(DataType.I32, 5)
        dim = struct.unpack("<I", result[8:12])[0]
        assert dim == 1

    def test_fixed_num_values(self):
        result = pack_raw_index(DataType.I32, 7)
        nv = struct.unpack("<Q", result[12:20])[0]
        assert nv == 7

    def test_string_size(self):
        result = pack_raw_index(DataType.STRING, 3, total_string_bytes=15)
        assert len(result) == 28

    def test_string_payload_len(self):
        result = pack_raw_index(DataType.STRING, 3, total_string_bytes=15)
        payload_len = struct.unpack("<I", result[:4])[0]
        assert payload_len == 20  # 4+4+8+8

    def test_string_total_bytes(self):
        result = pack_raw_index(DataType.STRING, 3, total_string_bytes=15)
        total = struct.unpack("<Q", result[20:28])[0]
        assert total == 15

    def test_string_missing_total_bytes_raises(self):
        with pytest.raises(ValueError, match="total_string_bytes"):
            pack_raw_index(DataType.STRING, 3)

    def test_no_data_index(self):
        assert pack_no_data_index() == struct.pack("<I", 0xFFFFFFFF)

    def test_same_index(self):
        assert pack_same_index() == struct.pack("<I", 0x00000000)


# ---------------------------------------------------------------------------
# pack_property
# ---------------------------------------------------------------------------

class TestPackProperty:
    def test_string_property_round_trip_fields(self):
        raw = pack_property("author", DataType.STRING, "Alice")
        # Name: u32(6) + b"author"
        assert raw[:4] == struct.pack("<I", 6)
        assert raw[4:10] == b"author"
        # Data type
        dtype = struct.unpack("<I", raw[10:14])[0]
        assert dtype == DataType.STRING
        # Value: u32(5) + b"Alice"
        assert raw[14:18] == struct.pack("<I", 5)
        assert raw[18:23] == b"Alice"

    def test_int_property(self):
        raw = pack_property("count", DataType.I32, 42)
        # Name
        assert raw[4:9] == b"count"
        # Data type
        dtype = struct.unpack("<I", raw[9:13])[0]
        assert dtype == DataType.I32
        # Value
        val = struct.unpack("<i", raw[13:17])[0]
        assert val == 42

    def test_float64_property(self):
        raw = pack_property("pi", DataType.FLOAT64, 3.14)
        val = struct.unpack("<d", raw[-8:])[0]
        assert abs(val - 3.14) < 1e-12


# ---------------------------------------------------------------------------
# pack_values
# ---------------------------------------------------------------------------

class TestPackValues:
    def test_int32_list(self):
        raw, n, extra = pack_values(DataType.I32, [1, 2, 3])
        assert n == 3
        assert extra is None
        assert raw == struct.pack("<iii", 1, 2, 3)

    def test_float64_list(self):
        raw, n, extra = pack_values(DataType.FLOAT64, [1.0, 2.0])
        assert n == 2
        assert raw == struct.pack("<dd", 1.0, 2.0)

    def test_boolean_list(self):
        raw, n, extra = pack_values(DataType.BOOLEAN, [True, False, True])
        assert raw == bytes([1, 0, 1])

    def test_timestamp_list(self):
        raw, n, extra = pack_values(DataType.TIMESTAMP, [(100, 0), (200, 0)])
        assert n == 2
        assert len(raw) == 32
        s0, f0 = struct.unpack_from("<qQ", raw, 0)
        s1, f1 = struct.unpack_from("<qQ", raw, 16)
        assert (s0, f0) == (100, 0)
        assert (s1, f1) == (200, 0)

    def test_string_offsets_and_payload(self):
        raw, n, total = pack_values(DataType.STRING, ["ab", "cde"])
        assert n == 2
        # END offsets: cumulative byte position of the end of each string
        off0 = struct.unpack_from("<I", raw, 0)[0]
        assert off0 == 2   # end of "ab"
        off1 = struct.unpack_from("<I", raw, 4)[0]
        assert off1 == 5   # end of "cde"
        # Total raw bytes: 4*n (offset array) + payload
        assert total == 4 * 2 + 5   # == 13
        # Payload
        assert raw[8:] == b"abcde"

    def test_string_single(self):
        raw, n, total = pack_values(DataType.STRING, ["hello"])
        assert n == 1
        # total_raw_bytes = 4*1 + 5 = 9
        assert total == 9
        # End offset of first (and only) string = 5
        off = struct.unpack_from("<I", raw, 0)[0]
        assert off == 5
        assert raw[4:] == b"hello"

    def test_empty_list(self):
        raw, n, extra = pack_values(DataType.I32, [])
        assert n == 0
        assert raw == b""


# ---------------------------------------------------------------------------
# validate_raw_bytes
# ---------------------------------------------------------------------------

class TestValidateRawBytes:
    def test_valid_i32(self):
        data = struct.pack("<iii", 1, 2, 3)
        n = validate_raw_bytes(DataType.I32, data, None)
        assert n == 3

    def test_valid_float32(self):
        data = struct.pack("<ff", 1.0, 2.0)
        n = validate_raw_bytes(DataType.FLOAT32, data, 2)
        assert n == 2

    def test_wrong_count_raises(self):
        data = struct.pack("<iii", 1, 2, 3)
        with pytest.raises(ValueError, match="Expected 2"):
            validate_raw_bytes(DataType.I32, data, 2)

    def test_non_multiple_raises(self):
        with pytest.raises(ValueError, match="multiple"):
            validate_raw_bytes(DataType.I32, b"\x00\x00\x01", None)

    def test_string_raises(self):
        with pytest.raises(ValueError, match="STRING"):
            validate_raw_bytes(DataType.STRING, b"hello", None)
