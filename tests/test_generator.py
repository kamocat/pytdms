"""
Unit tests for tdms.generator - TdmsSegmentGenerator with fixed channels.

These tests verify that the generator produces valid TDMS segments
(lead-in + metadata) for fixed interleaved data layouts.
"""

import struct
import tempfile
import os

import pytest

from tdms.channel import Channel
from tdms.constants import (
    LEAD_IN_SIZE,
    TAG,
    VERSION,
    TOC_DEFAULT_INTERLEAVED,
    DataType,
)
from tdms.generator import TdmsSegmentGenerator


class TestTdmsSegmentGenerator:
    """Test TdmsSegmentGenerator API and output."""

    def test_init_empty_channels_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            TdmsSegmentGenerator([])

    def test_init_calculates_scan_size(self):
        ch_i32 = Channel("G", "I32", DataType.I32)
        ch_f32 = Channel("G", "F32", DataType.FLOAT32)
        gen = TdmsSegmentGenerator([ch_i32, ch_f32])
        assert gen._scan_size == 8  # 4 + 4

    def test_build_metadata_returns_bytes(self):
        ch = Channel("Group", "Channel", DataType.I32)
        gen = TdmsSegmentGenerator([ch], file_properties={})
        result = gen.build_metadata(10)
        assert isinstance(result, bytes)
        assert len(result) > LEAD_IN_SIZE

    def test_lead_in_structure(self):
        ch = Channel("Group", "Channel", DataType.I32)
        gen = TdmsSegmentGenerator([ch], file_properties={})
        header = gen.build_metadata(10)
        
        lead_in = header[:LEAD_IN_SIZE]
        assert lead_in[:4] == TAG
        
        version = struct.unpack("<I", lead_in[8:12])[0]
        assert version == VERSION
        
        toc = struct.unpack("<I", lead_in[4:8])[0]
        assert toc & TOC_DEFAULT_INTERLEAVED

    def test_next_segment_offset_calculation(self):
        ch_i32 = Channel("G", "I32", DataType.I32)
        ch_f32 = Channel("G", "F32", DataType.FLOAT32)
        gen = TdmsSegmentGenerator([ch_i32, ch_f32], file_properties={})
        
        num_scans = 100
        header = gen.build_metadata(num_scans)
        lead_in = header[:LEAD_IN_SIZE]
        
        next_seg_offset = struct.unpack("<Q", lead_in[12:20])[0]
        meta_offset = struct.unpack("<Q", lead_in[20:28])[0]
        raw_data_size = num_scans * gen._scan_size
        
        assert next_seg_offset == meta_offset + raw_data_size

    def test_write_and_read_basic_file(self):
        ch_id = Channel("Sensors", "ID", DataType.I32)
        ch_time = Channel("Sensors", "Time", DataType.FLOAT32)
        gen = TdmsSegmentGenerator([ch_id, ch_time], file_properties={})
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tdms") as f:
            tmpfile = f.name
            try:
                header = gen.build_metadata(64)
                f.write(header)
                scans = b"\x00" * (64 * 8)
                f.write(scans)
                f.flush()
                
                with open(tmpfile, "rb") as rf:
                    read_tag = rf.read(4)
                    assert read_tag == TAG
            finally:
                os.unlink(tmpfile)

    def test_consistent_output(self):
        ch = Channel("G", "C", DataType.I32)
        gen = TdmsSegmentGenerator([ch], file_properties={})
        h1 = gen.build_metadata(50)
        h2 = gen.build_metadata(50)
        assert h1 == h2

    def test_multiple_channels_different_types(self):
        channels = [
            Channel("Data", "I8", DataType.I8),
            Channel("Data", "I16", DataType.I16),
            Channel("Data", "I32", DataType.I32),
            Channel("Data", "F32", DataType.FLOAT32),
            Channel("Data", "F64", DataType.FLOAT64),
            Channel("Data", "Bool", DataType.BOOLEAN),
        ]
        gen = TdmsSegmentGenerator(channels, file_properties={})
        expected_scan_size = 1 + 2 + 4 + 4 + 8 + 1
        assert gen._scan_size == expected_scan_size


class TestTdmsSegmentGeneratorNptdmsCompat:
    """Verify generated TDMS files are readable by nptdms library."""

    def test_generator_output_readable_by_nptdms(self):
        """Write a TDMS file with generator and read it back with nptdms."""
        try:
            from nptdms import TdmsFile
        except ImportError:
            pytest.skip("nptdms not available")
        
        import io
        
        # Create two channels with distinct data
        ch_id = Channel("Sensors", "ID", DataType.I32)
        ch_time = Channel("Sensors", "Time", DataType.FLOAT64)
        gen = TdmsSegmentGenerator([ch_id, ch_time])
        
        # Write segment: header + 10 interleaved scans
        num_scans = 10
        header = gen.build_metadata(num_scans)
        
        # Create interleaved data: [id0][time0][id1][time1]...[id9][time9]
        raw_scans = io.BytesIO()
        for i in range(num_scans):
            raw_scans.write(struct.pack("<i", i))  # I32 id
            raw_scans.write(struct.pack("<d", float(i) * 0.5))  # F64 time
        
        # Write to buffer
        buf = io.BytesIO()
        buf.write(header)
        buf.write(raw_scans.getvalue())
        buf.seek(0)
        
        # Read with nptdms
        tdms = TdmsFile.read(buf)
        
        # Verify structure
        groups = {g.name for g in tdms.groups()}
        assert "Sensors" in groups
        
        group = [g for g in tdms.groups() if g.name == "Sensors"][0]
        channels = {c.name for c in group.channels()}
        assert "ID" in channels
        assert "Time" in channels
        
        # Verify data round-trip
        id_ch = [c for c in group.channels() if c.name == "ID"][0]
        time_ch = [c for c in group.channels() if c.name == "Time"][0]
        
        id_data = id_ch.data
        time_data = time_ch.data
        
        assert len(id_data) == num_scans
        assert len(time_data) == num_scans
        
        for i in range(num_scans):
            assert id_data[i] == i
            assert time_data[i] == float(i) * 0.5

    def test_nptdms_file_properties(self):
        """Verify file properties are preserved through nptdms read."""
        try:
            from nptdms import TdmsFile
        except ImportError:
            pytest.skip("nptdms not available")
        
        import io
        from tdms.constants import DataType as DT
        
        ch = Channel("G", "C", DataType.FLOAT32)
        props = {
            "Description": (DT.STRING, "Test segment"),
            "Unit": (DT.STRING, "meters")
        }
        gen = TdmsSegmentGenerator([ch], file_properties=props)
        
        header = gen.build_metadata(5)
        buf = io.BytesIO()
        buf.write(header)
        buf.write(b"\x00" * 20)  # 5 scans × 4 bytes
        buf.seek(0)
        
        tdms = TdmsFile.read(buf)
        file_props = tdms.properties
        
        assert file_props.get("Description") == "Test segment"
        assert file_props.get("Unit") == "meters"

    def test_nptdms_multiple_channel_types(self):
        """Verify mixed data types work correctly with nptdms."""
        try:
            from nptdms import TdmsFile
        except ImportError:
            pytest.skip("nptdms not available")
        
        import io
        
        channels = [
            Channel("Mixed", "Bool", DataType.BOOLEAN),
            Channel("Mixed", "I32", DataType.I32),
            Channel("Mixed", "F64", DataType.FLOAT64),
        ]
        gen = TdmsSegmentGenerator(channels)
        
        header = gen.build_metadata(3)
        
        # Create 3 interleaved scans: [bool][i32][f64] repeated
        raw_scans = io.BytesIO()
        for i in range(3):
            raw_scans.write(struct.pack("<B", i % 2))  # Boolean (1 byte)
            raw_scans.write(struct.pack("<i", 1000 + i))  # I32
            raw_scans.write(struct.pack("<d", 3.14 + i))  # F64
        
        buf = io.BytesIO()
        buf.write(header)
        buf.write(raw_scans.getvalue())
        buf.seek(0)
        
        tdms = TdmsFile.read(buf)
        group = tdms.groups()[0]
        
        bool_ch = [c for c in group.channels() if c.name == "Bool"][0]
        i32_ch = [c for c in group.channels() if c.name == "I32"][0]
        f64_ch = [c for c in group.channels() if c.name == "F64"][0]
        
        bool_data = bool_ch.data
        i32_data = i32_ch.data
        f64_data = f64_ch.data
        
        assert len(bool_data) == 3
        assert len(i32_data) == 3
        assert len(f64_data) == 3
        
        for i in range(3):
            assert bool_data[i] == (i % 2)
            assert i32_data[i] == 1000 + i
            assert abs(f64_data[i] - (3.14 + i)) < 1e-10