"""
Async writer tests — mirrors test_writer.py but uses AsyncTdmsWriter.

Each test runs its coroutine via asyncio.run().  Tests that need nptdms
(file round-trips) require the nptdms extra.
"""

import asyncio
import struct
import pytest

from pytdms.constants import DataType, TAG, LEAD_IN_SIZE
from pytdms.channel import Channel
from tests.conftest import requires_nptdms, channel_data

try:
    from pytdms.async_writer import AsyncTdmsWriter
    HAS_ASYNC = True
except ImportError:
    HAS_ASYNC = False

pytestmark = pytest.mark.skipif(
    not HAS_ASYNC, reason="aiofile not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def count_tag(data):
    count = 0
    pos = 0
    while True:
        idx = data.find(TAG, pos)
        if idx == -1:
            break
        count += 1
        pos = idx + 1
    return count


# ---------------------------------------------------------------------------
# Basic writes
# ---------------------------------------------------------------------------

class TestAsyncBasic:
    def test_single_int32_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [1, 2, 3])])

        run(go())
        data = path.read_bytes()
        assert data[:4] == TAG
        assert data[-12:] == struct.pack("<iii", 1, 2, 3)

    def test_float64_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.FLOAT64)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [3.14, 2.72])])

        run(go())
        data = path.read_bytes()
        assert data[-16:] == struct.pack("<dd", 3.14, 2.72)

    def test_boolean_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.BOOLEAN)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [True, False, True])])

        run(go())
        assert path.read_bytes()[-3:] == bytes([1, 0, 1])

    def test_string_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.STRING)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, ["hello"])])

        run(go())
        data = path.read_bytes()
        assert data[-9:] == struct.pack("<I", 5) + b"hello"

    def test_pre_packed_bytes(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        raw = struct.pack("<iii", 7, 8, 9)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, raw)])

        run(go())
        assert path.read_bytes()[-12:] == raw


# ---------------------------------------------------------------------------
# Same-segment append optimisation
# ---------------------------------------------------------------------------

class TestAsyncAppend:
    def test_three_same_chunks_one_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                for i in range(3):
                    await w.write_segment([(ch, [i])])

        run(go())
        assert count_tag(path.read_bytes()) == 1

    def test_appended_data_contiguous(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [1, 2, 3])])
                await w.write_segment([(ch, [4, 5, 6])])

        run(go())
        data = path.read_bytes()
        assert data[-24:] == struct.pack("<iiiiii", 1, 2, 3, 4, 5, 6)

    def test_layout_change_creates_new_segment(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch1 = Channel("G", "C1", DataType.I32)
        ch2 = Channel("G", "C2", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch1, [1])])
                await w.write_segment([(ch1, [2]), (ch2, [3])])

        run(go())
        assert count_tag(path.read_bytes()) == 2


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestAsyncProperties:
    def test_channel_property_in_output(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        ch.add_property("unit", DataType.STRING, "Amps")

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [1])])

        run(go())
        assert b"Amps" in path.read_bytes()

    def test_file_property_in_output(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment(
                    [(ch, [1])],
                    file_properties={"title": (DataType.STRING, "MyTest")}
                )

        run(go())
        assert b"MyTest" in path.read_bytes()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestAsyncContextManager:
    def test_close_called_on_exit(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        writer_ref = []

        async def go():
            w = AsyncTdmsWriter(str(path))
            async with w:
                await w.write_segment([(ch, [42])])
            writer_ref.append(w)

        run(go())
        assert writer_ref[0]._afile is None

    def test_exception_still_closes(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)
        writer_ref = []

        async def go():
            w = AsyncTdmsWriter(str(path))
            try:
                async with w:
                    await w.write_segment([(ch, [1])])
                    raise RuntimeError("test")
            except RuntimeError:
                pass
            writer_ref.append(w)

        run(go())
        assert writer_ref[0]._afile is None


# ---------------------------------------------------------------------------
# nptdms round-trip via async writer
# ---------------------------------------------------------------------------

class TestAsyncNptdmsRoundTrip:
    @requires_nptdms
    def test_float64_round_trip(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("Sensors", "Temp", DataType.FLOAT64)
        expected = [1.1, 2.2, 3.3]

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, expected)])

        run(go())
        import numpy as np
        result = channel_data(path, "Sensors", "Temp")
        np.testing.assert_allclose(result, expected, rtol=1e-15)

    @requires_nptdms
    def test_multi_chunk_accumulation(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.I32)

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, [1, 2, 3])])
                await w.write_segment([(ch, [4, 5, 6])])

        run(go())
        import numpy as np
        result = channel_data(path, "G", "C")
        np.testing.assert_array_equal(result, [1, 2, 3, 4, 5, 6])

    @requires_nptdms
    def test_string_channel_round_trip(self, tmp_path):
        path = tmp_path / "test.tdms"
        ch = Channel("G", "C", DataType.STRING)
        vals = ["alpha", "beta", "gamma"]

        async def go():
            async with AsyncTdmsWriter(str(path)) as w:
                await w.write_segment([(ch, vals)])

        run(go())
        result = channel_data(path, "G", "C")
        assert list(result) == vals
