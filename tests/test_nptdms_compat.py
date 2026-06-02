"""
nptdms compatibility tests — write with pytdms, read back with nptdms.

Every test follows the same pattern:
  1. Write a TDMS file with TdmsWriter
  2. Read it with nptdms.TdmsFile.read()
  3. Assert data / properties / structure match expectations
"""

import struct

import numpy as np

from pytdms.channel import Channel
from pytdms.constants import DataType
from pytdms.writer import TdmsWriter
from tests.conftest import (
    channel_data,
    channel_properties,
    file_properties,
    read_tdms,
    requires_nptdms,
)

pytestmark = requires_nptdms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_simple(tmp_path, data_type, values, group="G", name="C", ch_props=None):
    """Write a single-channel file and return its path."""
    path = tmp_path / "test.tdms"
    ch = Channel(group, name, data_type, properties=ch_props)
    with TdmsWriter(str(path)) as w:
        w.write_segment([(ch, values)])
    return path


# ---------------------------------------------------------------------------
# All numeric data types
# ---------------------------------------------------------------------------


class TestNumericTypes:
    def test_i8(self, tmp_path):
        vals = [-128, -1, 0, 1, 127]
        path = write_simple(tmp_path, DataType.I8, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.int8))

    def test_i16(self, tmp_path):
        vals = [-32768, 0, 32767]
        path = write_simple(tmp_path, DataType.I16, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.int16))

    def test_i32(self, tmp_path):
        vals = [-(2**31), 0, 2**31 - 1]
        path = write_simple(tmp_path, DataType.I32, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.int32))

    def test_i64(self, tmp_path):
        vals = [-(2**62), 0, 2**62]
        path = write_simple(tmp_path, DataType.I64, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.int64))

    def test_u8(self, tmp_path):
        vals = [0, 128, 255]
        path = write_simple(tmp_path, DataType.U8, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.uint8))

    def test_u16(self, tmp_path):
        vals = [0, 1000, 65535]
        path = write_simple(tmp_path, DataType.U16, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.uint16))

    def test_u32(self, tmp_path):
        vals = [0, 100000, 0xFFFFFFFF]
        path = write_simple(tmp_path, DataType.U32, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.uint32))

    def test_u64(self, tmp_path):
        vals = [0, 2**63]
        path = write_simple(tmp_path, DataType.U64, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=np.uint64))

    def test_float32(self, tmp_path):
        vals = [-1.5, 0.0, 3.14]
        path = write_simple(tmp_path, DataType.FLOAT32, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_allclose(result, np.array(vals, dtype=np.float32), rtol=1e-6)

    def test_float64(self, tmp_path):
        vals = [-1.234567890123, 0.0, 9.876543210987]
        path = write_simple(tmp_path, DataType.FLOAT64, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_allclose(result, np.array(vals, dtype=np.float64), rtol=1e-15)

    def test_boolean(self, tmp_path):
        vals = [True, False, True, True, False]
        path = write_simple(tmp_path, DataType.BOOLEAN, vals)
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, np.array(vals, dtype=bool))


# ---------------------------------------------------------------------------
# String channels
# ---------------------------------------------------------------------------


class TestStringChannel:
    def test_single_value(self, tmp_path):
        path = write_simple(tmp_path, DataType.STRING, ["hello"])
        result = channel_data(path, "G", "C")
        assert list(result) == ["hello"]

    def test_multiple_values(self, tmp_path):
        vals = ["alpha", "beta", "gamma"]
        path = write_simple(tmp_path, DataType.STRING, vals)
        result = channel_data(path, "G", "C")
        assert list(result) == vals

    def test_utf8_content(self, tmp_path):
        vals = ["héllo", "wörld", "日本語"]
        path = write_simple(tmp_path, DataType.STRING, vals)
        result = channel_data(path, "G", "C")
        assert list(result) == vals

    def test_empty_string(self, tmp_path):
        path = write_simple(tmp_path, DataType.STRING, [""])
        result = channel_data(path, "G", "C")
        assert list(result) == [""]


# ---------------------------------------------------------------------------
# Timestamp channels
# ---------------------------------------------------------------------------


class TestTimestampChannel:
    def test_basic_timestamp(self, tmp_path):
        # NI epoch: 1904-01-01; Unix epoch: 1970-01-01
        # We use (0, 0) which corresponds to 1904-01-01 00:00:00 UTC
        path = write_simple(tmp_path, DataType.TIMESTAMP, [(0, 0)])
        result = channel_data(path, "G", "C")
        # nptdms returns datetime64; verify it's readable (not error)
        assert len(result) == 1

    def test_multiple_timestamps(self, tmp_path):
        ts_vals = [(100, 0), (200, 0), (300, 0)]
        path = write_simple(tmp_path, DataType.TIMESTAMP, ts_vals)
        result = channel_data(path, "G", "C")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Multi-segment accumulation
# ---------------------------------------------------------------------------


class TestMultiSegment:
    def test_two_segments_data_accumulates(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1, 2, 3])])
            w.write_segment([(ch, [4, 5, 6, 7])])  # different count → new segment
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, [1, 2, 3, 4, 5, 6, 7])

    def test_same_layout_chunks_accumulate(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.FLOAT64)
        all_vals = []
        with TdmsWriter(str(path)) as w:
            for i in range(5):
                chunk = [float(i * 10 + j) for j in range(3)]
                all_vals.extend(chunk)
                w.write_segment([(ch, chunk)])
        result = channel_data(path, "G", "C")
        np.testing.assert_allclose(result, np.array(all_vals))

    def test_channel_added_mid_stream(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch1 = Channel("G", "C1", DataType.I32)
        ch2 = Channel("G", "C2", DataType.I32)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch1, [10, 20])])
            w.write_segment([(ch1, [30]), (ch2, [100])])
        r1 = channel_data(path, "G", "C1")
        r2 = channel_data(path, "G", "C2")
        np.testing.assert_array_equal(r1, [10, 20, 30])
        np.testing.assert_array_equal(r2, [100])


# ---------------------------------------------------------------------------
# Multiple groups
# ---------------------------------------------------------------------------


class TestMultipleGroups:
    def test_two_groups_readable(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch1 = Channel("Sensors", "Temp", DataType.FLOAT32)
        ch2 = Channel("Control", "Voltage", DataType.FLOAT32)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch1, [25.0, 26.0]), (ch2, [3.3, 3.4])])
        tdms = read_tdms(path)
        groups = [g.name for g in tdms.groups()]
        assert "Sensors" in groups
        assert "Control" in groups

    def test_two_groups_data_correct(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch1 = Channel("GroupA", "X", DataType.FLOAT64)
        ch2 = Channel("GroupB", "Y", DataType.FLOAT64)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch1, [1.0, 2.0]), (ch2, [3.0, 4.0])])
        np.testing.assert_allclose(channel_data(path, "GroupA", "X"), [1.0, 2.0])
        np.testing.assert_allclose(channel_data(path, "GroupB", "Y"), [3.0, 4.0])


# ---------------------------------------------------------------------------
# Properties round-trip
# ---------------------------------------------------------------------------


class TestPropertiesRoundTrip:
    def test_channel_string_property(self, tmp_path):
        ch = Channel("G", "C", DataType.FLOAT64)
        ch.add_property("unit_string", DataType.STRING, "Volts")
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1.0])])
        props = channel_properties(path, "G", "C")
        assert props["unit_string"] == "Volts"

    def test_channel_int_property(self, tmp_path):
        ch = Channel("G", "C", DataType.FLOAT32)
        ch.add_property("sensor_id", DataType.I32, 42)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [0.0])])
        props = channel_properties(path, "G", "C")
        assert props["sensor_id"] == 42

    def test_channel_float_property(self, tmp_path):
        ch = Channel("G", "C", DataType.FLOAT64)
        ch.add_property("scale", DataType.FLOAT64, 0.001)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1.0])])
        props = channel_properties(path, "G", "C")
        assert abs(props["scale"] - 0.001) < 1e-12

    def test_channel_bool_property(self, tmp_path):
        ch = Channel("G", "C", DataType.I32)
        ch.add_property("enabled", DataType.BOOLEAN, True)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1])])
        props = channel_properties(path, "G", "C")
        assert props["enabled"] is True

    def test_file_string_property(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1])], file_properties={"author": (DataType.STRING, "Alice")})
        props = file_properties(path)
        assert props["author"] == "Alice"

    def test_file_int_property(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1])], file_properties={"version": (DataType.I32, 3)})
        props = file_properties(path)
        assert props["version"] == 3

    def test_multiple_channel_properties(self, tmp_path):
        ch = Channel("G", "C", DataType.FLOAT64)
        ch.add_property("unit_string", DataType.STRING, "°C")
        ch.add_property("wf_increment", DataType.FLOAT64, 0.001)
        ch.add_property("samples", DataType.I32, 100)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [20.0])])
        props = channel_properties(path, "G", "C")
        assert props["unit_string"] == "°C"
        assert abs(props["wf_increment"] - 0.001) < 1e-12
        assert props["samples"] == 100


# ---------------------------------------------------------------------------
# Special characters in names
# ---------------------------------------------------------------------------


class TestSpecialNamesCompat:
    def test_group_with_single_quote(self, tmp_path):
        ch = Channel("Dr. T's Lab", "Ch", DataType.I32)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [1, 2, 3])])
        result = channel_data(path, "Dr. T's Lab", "Ch")
        np.testing.assert_array_equal(result, [1, 2, 3])

    def test_channel_with_single_quote(self, tmp_path):
        ch = Channel("G", "it's data", DataType.I32)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [7, 8])])
        result = channel_data(path, "G", "it's data")
        np.testing.assert_array_equal(result, [7, 8])


# ---------------------------------------------------------------------------
# Pre-packed bytes input round-trip
# ---------------------------------------------------------------------------


class TestPrePackedBytesCompat:
    def test_float64_bytes_input(self, tmp_path):
        ch = Channel("G", "C", DataType.FLOAT64)
        expected = [1.1, 2.2, 3.3]
        raw = struct.pack("<ddd", *expected)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, raw)])
        result = channel_data(path, "G", "C")
        np.testing.assert_allclose(result, expected, rtol=1e-15)

    def test_int32_bytearray_input(self, tmp_path):
        ch = Channel("G", "C", DataType.I32)
        expected = [10, 20, 30, 40]
        raw = bytearray(struct.pack("<iiii", *expected))
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, raw)])
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, expected)


# ---------------------------------------------------------------------------
# Waveform pattern (predefined properties)
# ---------------------------------------------------------------------------


class TestWaveformPattern:
    def test_wf_properties_readable(self, tmp_path):
        ch = Channel("Waveforms", "Signal", DataType.FLOAT64)
        ch.add_property("wf_increment", DataType.FLOAT64, 0.001)
        ch.add_property("wf_start_offset", DataType.FLOAT64, 0.0)
        ch.add_property("wf_samples", DataType.I32, 3)
        path = tmp_path / "test.tdms"
        with TdmsWriter(str(path)) as w:
            w.write_segment([(ch, [0.1, 0.2, 0.3])])
        props = channel_properties(path, "Waveforms", "Signal")
        assert abs(props["wf_increment"] - 0.001) < 1e-15
        assert props["wf_samples"] == 3
