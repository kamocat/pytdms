"""
CircuitPython write-performance benchmark
==========================================
Compares interleaved vs contiguous (non-interleaved) TDMS write performance
for a realistic multi-channel sensor logging scenario.

Compatible with CircuitPython 10.x and CPython 3.8+.
No asyncio, no pathlib, no typing, no walrus operator.

Interleaved layout  (default):
    [ch0_s0][ch1_s0][ch2_s0][ch0_s1][ch1_s1][ch2_s1]...
    Scan order matches the order data arrives from hardware, so fewer
    intermediate copies are needed when the caller already has one
    interleaved buffer (e.g. from an ADC DMA transfer).

Contiguous layout:
    [ch0_s0][ch0_s1]...[ch1_s0][ch1_s1]...[ch2_s0][ch2_s1]...
    Better for readers that access one channel at a time in bulk.

Run on CircuitPython:
    Copy this file and the pytdms/ folder to your CIRCUITPY drive, then
    open a serial console (e.g. Mu editor) and import or run it.
    An SD card is required — the script mounts it at /sd automatically.
    Adjust the ``board.SD_CS`` pin constant if your board uses a different pin.

Run on CPython (development / CI):
    python examples/circuitpython_write_benchmark.py
"""

import struct
import sys
import time

from pytdms import Channel, DataType, TdmsWriter

# ---------------------------------------------------------------------------
# CircuitPython: mount SD card at /sd
# ---------------------------------------------------------------------------
if sys.implementation.name == "circuitpython":
    import board
    import sdcardio
    import storage

    _spi = board.SPI()
    _sd = sdcardio.SDCard(_spi, board.SD_CS)  # change SD_CS to match your board
    storage.mount(storage.VfsFat(_sd), "/sd")
    OUTPUT_DIR = "/sd"
else:
    OUTPUT_DIR = "."

# ---------------------------------------------------------------------------
# Benchmark parameters — adjust to match your target hardware / use-case
# ---------------------------------------------------------------------------

# Number of channels to log simultaneously (e.g. 4 ADC inputs)
NUM_CHANNELS = 6

# Number of samples written per channel per write_segment() call
SAMPLES_PER_CHUNK = 32

# How many write_segment() calls to make per run
NUM_CHUNKS = 2000

# Data type for all channels  (fixed-width only — strings cannot be interleaved)
CHANNEL_TYPE = DataType.FLOAT32

# ---------------------------------------------------------------------------
# Channel definitions
# ---------------------------------------------------------------------------

CHANNELS = [Channel("Sensors", f"Ch{i}", CHANNEL_TYPE) for i in range(NUM_CHANNELS)]

# ---------------------------------------------------------------------------
# Build one chunk of sample data (reused across all calls to avoid measuring
# list/struct allocation time, which is the same for both modes).
# ---------------------------------------------------------------------------
# Each channel gets a repeating ramp:  i * 0.01  (FLOAT32)
_CHUNK = [
    [float(s + ch * SAMPLES_PER_CHUNK) * 0.01 for s in range(SAMPLES_PER_CHUNK)]
    for ch in range(NUM_CHANNELS)
]

# Pre-pack to raw bytes so the benchmark measures I/O + interleaving, not
# Python list-to-bytes conversion (which is identical for both modes).
_RAW_CHUNKS = [struct.pack(f"<{SAMPLES_PER_CHUNK}f", *_CHUNK[ch]) for ch in range(NUM_CHANNELS)]

# Build scan-ordered buffer for write_interleaved_segment:
# [ch0_s0][ch1_s0]...[chN_s0][ch0_s1][ch1_s1]...
_BYTES_PER_SAMPLE = 4  # FLOAT32
_scan_parts = []
for _s in range(SAMPLES_PER_CHUNK):
    for _ch in range(NUM_CHANNELS):
        _scan_parts.append(_RAW_CHUNKS[_ch][_s * _BYTES_PER_SAMPLE : (_s + 1) * _BYTES_PER_SAMPLE])
_SCAN_CHUNK = b"".join(_scan_parts)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(mode, output_path):
    """Write NUM_CHUNKS × SAMPLES_PER_CHUNK samples to *output_path*.

    *mode* is ``"interleaved"`` (uses write_interleaved_segment) or
    ``"contiguous"`` (uses write_segment with per-channel raw bytes).
    Returns elapsed seconds (float).
    """
    t0 = time.monotonic()
    with TdmsWriter(output_path) as w:
        for _ in range(NUM_CHUNKS):
            if mode == "interleaved":
                w.write_interleaved_segment(CHANNELS, _SCAN_CHUNK)
            else:
                w.write_segment(list(zip(CHANNELS, _RAW_CHUNKS)))
    elapsed = time.monotonic() - t0
    return elapsed


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------


def run_benchmark():
    path_il = OUTPUT_DIR + "/bench_interleaved.tdms"
    path_con = OUTPUT_DIR + "/bench_contiguous.tdms"

    total_samples = NUM_CHUNKS * SAMPLES_PER_CHUNK
    type_size = 4  # FLOAT32 = 4 bytes
    total_bytes = NUM_CHANNELS * total_samples * type_size

    print("=" * 56)
    print("pytdms write-performance benchmark")
    print("=" * 56)
    print(f"  Channels         : {NUM_CHANNELS}")
    print(f"  Samples/chunk    : {SAMPLES_PER_CHUNK}")
    print(f"  Chunks           : {NUM_CHUNKS}")
    print(f"  Total samples/ch : {total_samples}")
    print(f"  Payload bytes    : {total_bytes}")
    print("-" * 56)

    elapsed_il = _run(mode="interleaved", output_path=path_il)
    elapsed_con = _run(mode="contiguous", output_path=path_con)

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

    # Verify both files contain the same number of raw payload bytes
    # (layout differs but total data size must be identical).
    with open(path_il, "rb") as f:
        size_il = len(f.read())
    with open(path_con, "rb") as f:
        size_con = len(f.read())

    if size_il == size_con:
        print(f"  File size check  : OK ({size_il} bytes each)")
    else:
        print(f"  File size check  : MISMATCH ({size_il} vs {size_con})")

    print("")


run_benchmark()
