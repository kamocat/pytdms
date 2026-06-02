"""
Pre-packed data example
=======================
When data is already in binary form — e.g. read from a UART/SPI buffer,
a DMA transfer, or a struct.pack call — you can pass it directly to
write_segment() without any intermediate Python list allocation.

Rules
-----
* The data must be a bytes, bytearray, or memoryview object.
* The byte layout must be little-endian, matching the channel's DataType.
* The total length must be an exact multiple of the type's byte size.
* The number of samples written equals len(data) // type_size.
* STRING channels do NOT accept pre-packed bytes (strings require the
  offset-array wire format that pytdms builds for you; pass a list of str).

Type sizes
----------
  DataType.I8      / U8      :  1 byte  per sample
  DataType.I16     / U16     :  2 bytes per sample
  DataType.I32     / U32     :  4 bytes per sample
  DataType.I64     / U64     :  8 bytes per sample
  DataType.FLOAT32           :  4 bytes per sample  (IEEE 754 single)
  DataType.FLOAT64           :  8 bytes per sample  (IEEE 754 double)
  DataType.BOOLEAN           :  1 byte  per sample  (0x00 = False, 0x01 = True)
  DataType.TIMESTAMP         : 16 bytes per sample  (i64 seconds + u64 fractions)
"""

import struct

from pytdms import Channel, DataType, TdmsWriter

OUTPUT_FILE = "prepacked_output.tdms"


# ---------------------------------------------------------------------------
# 1. Packing manually with struct.pack
# ---------------------------------------------------------------------------
# struct format characters that match each DataType (always little-endian '<'):
#
#   DataType.I8      -> '<b'   DataType.U8      -> '<B'
#   DataType.I16     -> '<h'   DataType.U16     -> '<H'
#   DataType.I32     -> '<i'   DataType.U32     -> '<I'
#   DataType.I64     -> '<q'   DataType.U64     -> '<Q'
#   DataType.FLOAT32 -> '<f'
#   DataType.FLOAT64 -> '<d'
#   DataType.BOOLEAN -> '<B'   (0 = False, 1 = True)
#   DataType.TIMESTAMP -> '<qQ' per sample (i64 ni_seconds, u64 fractions)

# Simulate 8 ADC samples arriving as a raw I16 buffer (e.g. from SPI DMA)
adc_raw: bytes = struct.pack("<hhhhhhhh", 100, 200, -300, 400, -500, 600, -700, 800)

# A FLOAT32 engineering-unit channel packed ahead of time
eu_raw: bytes = struct.pack("<ffff", 1.0, 2.5, -1.5, 0.0)

# A BOOLEAN channel packed as individual bytes
bool_raw: bytes = bytes([1, 0, 1, 1, 0, 0, 1, 0])

# A TIMESTAMP channel: two samples, fractions = 0 for simplicity
# NI epoch is 1904-01-01; Unix epoch 1970-01-01 differs by 2 082 844 800 s.
NI_EPOCH_OFFSET = 2_082_844_800
ts_raw: bytes = struct.pack(
    "<qQqQ",
    NI_EPOCH_OFFSET + 1_000_000,
    0,  # sample 0: 1970-01-12 13:46:40 UTC
    NI_EPOCH_OFFSET + 2_000_000,
    0,  # sample 1: 1970-01-24 03:33:20 UTC
)


# ---------------------------------------------------------------------------
# 2. Packing from a memoryview (zero-copy slice of a larger buffer)
# ---------------------------------------------------------------------------
large_buffer = bytearray(struct.pack("<IIIIIIII", 10, 20, 30, 40, 50, 60, 70, 80))
# Only send the first 4 samples — no copy needed
u32_slice = memoryview(large_buffer)[:16]  # 4 × 4 bytes


# ---------------------------------------------------------------------------
# 3. Writing to a TDMS file
# ---------------------------------------------------------------------------
ch_adc = Channel("Sensors", "ADC_Raw", DataType.I16)
ch_eu = Channel("Sensors", "EU_Signal", DataType.FLOAT32)
ch_bool = Channel("Sensors", "Gate", DataType.BOOLEAN)
ch_ts = Channel("Sensors", "Timestamp", DataType.TIMESTAMP)
ch_u32 = Channel("Control", "Counter", DataType.U32)

with TdmsWriter(OUTPUT_FILE) as writer:
    # First chunk: all channels, first batch of data
    writer.write_segment(
        [
            (ch_adc, adc_raw),
            (ch_eu, eu_raw),
            (ch_bool, bool_raw),
            (ch_ts, ts_raw),
            (ch_u32, u32_slice),
        ]
    )

    # Subsequent chunks using the SAME channel layout reuse the open segment
    # (the same-segment append optimisation) — only raw bytes are written, no
    # metadata overhead.
    for i in range(4):
        next_adc = struct.pack("<hhhhhhhh", *(j + i * 10 for j in range(8)))
        next_eu = struct.pack("<ffff", float(i), float(i) + 0.5, -float(i), 0.0)
        next_bool = bytes([i % 2] * 8)
        next_ts = struct.pack(
            "<qQqQ",
            NI_EPOCH_OFFSET + (3 + i) * 1_000_000,
            0,
            NI_EPOCH_OFFSET + (4 + i) * 1_000_000,
            0,
        )
        next_u32 = struct.pack("<IIII", *range(i * 4, i * 4 + 4))

        writer.write_segment(
            [
                (ch_adc, next_adc),
                (ch_eu, next_eu),
                (ch_bool, next_bool),
                (ch_ts, next_ts),
                (ch_u32, next_u32),
            ]
        )

print("Written:", OUTPUT_FILE)

# ---------------------------------------------------------------------------
# 4. Verify with nptdms (optional — requires: pip install nptdms)
# ---------------------------------------------------------------------------
try:
    import nptdms

    tdms = nptdms.TdmsFile.read(OUTPUT_FILE)
    adc_ch = tdms["Sensors"]["ADC_Raw"]
    print("ADC_Raw sample count :", len(adc_ch[:]))
    print("ADC_Raw first 8 vals :", adc_ch[:8].tolist())
    print("EU_Signal first 4    :", tdms["Sensors"]["EU_Signal"][:4].tolist())
    print("Gate first 8         :", tdms["Sensors"]["Gate"][:8].tolist())
    print("Counter first 4      :", tdms["Control"]["Counter"][:4].tolist())
except ImportError:
    print("(Install nptdms to verify: pip install nptdms)")
