"""
asyncio write-performance benchmark (CircuitPython)
====================================================
Compares interleaved vs contiguous (non-interleaved) TDMS write performance
using AsyncTdmsWriter with an asyncfat-backed SD card.

Requires: abusio, asdcardio, asyncfat (aiofile package)

Copy this file and the pytdms/ folder to your CIRCUITPY drive, then
open a serial console (e.g. Mu editor) and run it.
Adjust the board.GP* pin constants to match your wiring.
"""

import asyncio
import struct
import time

import abusio
import asdcardio
import asyncfat
import board

from pytdms import Channel, DataType
from pytdms.async_writer import AsyncTdmsWriter

# ---------------------------------------------------------------------------
# Mount SD card at /sd
# ---------------------------------------------------------------------------

SD_BAUDRATE = 25_000_000  # 25 MHz — SD SPI standard speed mode max

_spi = abusio.SPI(MISO=board.GP16, clock=board.GP18, MOSI=board.GP19)
_sd = asdcardio.ASdCard(_spi, board.GP17, baudrate=SD_BAUDRATE)
print(f"SD OK — {_sd.count()} sectors @ {SD_BAUDRATE // 1_000_000} MHz")
OUTPUT_DIR = "/"

# ---------------------------------------------------------------------------
# Benchmark parameters
# ---------------------------------------------------------------------------

NUM_CHANNELS = 6
SAMPLES_PER_CHUNK = 32
NUM_CHUNKS = 2000
CHANNEL_TYPE = DataType.FLOAT32

# ---------------------------------------------------------------------------
# Channel definitions
# ---------------------------------------------------------------------------

CHANNELS = [Channel("Sensors", f"Ch{i}", CHANNEL_TYPE) for i in range(NUM_CHANNELS)]

# ---------------------------------------------------------------------------
# Pre-built data buffers (same layout as circuitpython_write_benchmark.py)
# ---------------------------------------------------------------------------

_CHUNK = [
    [float(s + ch * SAMPLES_PER_CHUNK) * 0.01 for s in range(SAMPLES_PER_CHUNK)]
    for ch in range(NUM_CHANNELS)
]

_RAW_CHUNKS = [struct.pack(f"<{SAMPLES_PER_CHUNK}f", *_CHUNK[ch]) for ch in range(NUM_CHANNELS)]

_BYTES_PER_SAMPLE = 4  # FLOAT32
_scan_parts = []
for _s in range(SAMPLES_PER_CHUNK):
    for _ch in range(NUM_CHANNELS):
        _scan_parts.append(_RAW_CHUNKS[_ch][_s * _BYTES_PER_SAMPLE : (_s + 1) * _BYTES_PER_SAMPLE])
_SCAN_CHUNK = b"".join(_scan_parts)


# ---------------------------------------------------------------------------
# Async runner
# ---------------------------------------------------------------------------


async def _run(mode, output_path):
    """Write NUM_CHUNKS x SAMPLES_PER_CHUNK samples asynchronously.

    Returns elapsed wall-clock seconds (float).
    """
    t0 = time.monotonic()
    async with AsyncTdmsWriter(output_path, sd=_sd) as w:
        for _ in range(NUM_CHUNKS):
            if mode == "interleaved":
                await w.write_interleaved_segment(CHANNELS, _SCAN_CHUNK)
            else:
                await w.write_segment(list(zip(CHANNELS, _RAW_CHUNKS)))
    return time.monotonic() - t0


async def get_size(fname):
    f = await asyncfat.async_open(_sd, fname, "r")
    size = f._size
    await f.close()
    return size


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------


async def run_benchmark():
    path_il = OUTPUT_DIR + "/async_bench_interleaved.tdms"
    path_con = OUTPUT_DIR + "/async_bench_contiguous.tdms"

    total_samples = NUM_CHUNKS * SAMPLES_PER_CHUNK
    type_size = 4  # FLOAT32
    total_bytes = NUM_CHANNELS * total_samples * type_size

    print("=" * 56)
    print("pytdms async write-performance benchmark")
    print("=" * 56)
    print(f"  Channels         : {NUM_CHANNELS}")
    print(f"  Samples/chunk    : {SAMPLES_PER_CHUNK}")
    print(f"  Chunks           : {NUM_CHUNKS}")
    print(f"  Total samples/ch : {total_samples}")
    print(f"  Payload bytes    : {total_bytes}")
    print("-" * 56)

    print(path_il)
    elapsed_il = await _run(mode="interleaved", output_path=path_il)
    print(path_con)
    elapsed_con = await _run(mode="contiguous", output_path=path_con)

    throughput_il = total_bytes / elapsed_il / 1024
    throughput_con = total_bytes / elapsed_con / 1024

    print(f"  Interleaved      : {elapsed_il:.3f} s  ({throughput_il:.1f} KB/s)")
    print(f"  Contiguous       : {elapsed_con:.3f} s  ({throughput_con:.1f} KB/s)")

    if elapsed_il < elapsed_con:
        speedup = (elapsed_con - elapsed_il) / elapsed_con * 100.0
        print(f"  Result           : interleaved is {speedup:.1f}% faster")
    elif elapsed_con < elapsed_il:
        speedup = (elapsed_il - elapsed_con) / elapsed_il * 100.0
        print(f"  Result           : contiguous is {speedup:.1f}% faster")
    else:
        print("  Result           : no measurable difference")

    print("=" * 56)

    size_il = await get_size(path_il)
    size_con = await get_size(path_con)

    if size_il == size_con:
        print(f"  File size check  : OK ({size_il} bytes each)")
    else:
        print(f"  File size check  : MISMATCH ({size_il} vs {size_con})")

    print("")


asyncio.run(run_benchmark())
