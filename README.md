# pytdms

Pure-Python streaming TDMS writer. CircuitPython 10.x compatible, zero dependencies for the core writer. Supports async I/O via `aiofile` on CPython.

## Features

- **Streaming** — write data chunk by chunk; the file is always valid on disk after every `write_segment` call
- **Same-segment append optimisation** — when the same channel layout is written repeatedly, only raw bytes are appended and the lead-in offset is patched in place (one 8-byte seek). No metadata rewrite per chunk
- **Dual input modes** — pass Python lists/tuples (the library packs them) or raw `bytes`/`bytearray`/`memoryview` (zero-copy, direct from DMA buffers)
- **Full data-type support** — I8/16/32/64, U8/16/32/64, FLOAT32, FLOAT64, BOOLEAN, STRING, TIMESTAMP
- **CircuitPython 10.x compatible** — no `enum`, no `asyncio`, no `dataclasses`, no walrus operator; only `struct` + `bytearray`
- **Async writer** — `AsyncTdmsWriter` uses `aiofile` for non-blocking I/O on CPython 3.8+
- **Verified against nptdms** — 144 tests including full round-trip checks for every data type

## Installation

```bash
# Core writer only
pip install pytdms

# With async support
pip install "pytdms[async]"

# With test dependencies
pip install "pytdms[test]"
```

For CircuitPython: copy the `pytdms/` folder to your `CIRCUITPY/lib/` directory.

## Quick start

```python
from pytdms import TdmsWriter, Channel, DataType

ch_temp  = Channel("Sensors", "Temperature", DataType.FLOAT32)
ch_count = Channel("Sensors", "SampleCount", DataType.U32)

# Optional channel properties
ch_temp.add_property("unit_string", DataType.STRING, "°C")
ch_temp.add_property("wf_increment", DataType.FLOAT64, 0.001)

with TdmsWriter("output.tdms") as writer:
    # Pass Python lists — the library handles packing
    writer.write_segment([
        (ch_temp,  [23.1, 23.4, 23.2]),
        (ch_count, [0, 1, 2]),
    ])

    # Repeated calls with the same layout share one TDMS segment
    # (metadata written only once; subsequent calls are raw-data appends)
    for i in range(100):
        writer.write_segment([
            (ch_temp,  [23.0 + i * 0.01] * 3),
            (ch_count, [i * 3, i * 3 + 1, i * 3 + 2]),
        ])
```

## Pre-packed binary data

When data arrives as a raw buffer (SPI/UART DMA, `struct.pack`, `array.array`), pass it directly:

```python
import struct
from pytdms import TdmsWriter, Channel, DataType

# struct format characters (all little-endian '<'):
#   I8/U8   -> b/B (1 byte)    I16/U16 -> h/H (2 bytes)
#   I32/U32 -> i/I (4 bytes)   I64/U64 -> q/Q (8 bytes)
#   FLOAT32 -> f (4 bytes)     FLOAT64 -> d (8 bytes)
#   BOOLEAN -> B (1 byte, 0=False 1=True)
#   TIMESTAMP -> qQ per sample (16 bytes: i64 NI-epoch-seconds + u64 fractions)

ch = Channel("ADC", "Raw", DataType.I16)
raw_buf = struct.pack("<hhhh", 100, 200, -300, 400)  # 4 samples from DMA

with TdmsWriter("adc.tdms") as writer:
    writer.write_segment([(ch, raw_buf)])

    # memoryview works too — zero copy
    large_buf = bytearray(1024)
    writer.write_segment([(ch, memoryview(large_buf)[:64])])
```

See [examples/prepacked_data.py](examples/prepacked_data.py) for a complete walkthrough.

## Async writer

```python
import asyncio
from pytdms.async_writer import AsyncTdmsWriter
from pytdms import Channel, DataType

ch = Channel("Sensors", "Voltage", DataType.FLOAT64)

async def main():
    async with AsyncTdmsWriter("output.tdms") as writer:
        await writer.write_segment([(ch, [1.0, 2.0, 3.0])])
        await writer.write_segment([(ch, [4.0, 5.0, 6.0])])

asyncio.run(main())
```

## File properties

```python
writer.write_segment(
    [(ch, data)],
    file_properties={
        "author":      (DataType.STRING, "Alice"),
        "description": (DataType.STRING, "Bench test #7"),
        "version":     (DataType.I32,    3),
    }
)
```

## TDMS object hierarchy

| Object | Path format | Created by |
|--------|-------------|------------|
| File   | `/`         | Automatically on first `write_segment` |
| Group  | `/'name'`   | Automatically when a new group appears |
| Channel| `/'group'/'channel'` | User-defined via `Channel(...)` |

## Data types

| `DataType` constant | TDMS type | `struct` fmt | Size |
|---------------------|-----------|--------------|------|
| `I8` | tdsTypeI8 | `<b` | 1 byte |
| `I16` | tdsTypeI16 | `<h` | 2 bytes |
| `I32` | tdsTypeI32 | `<i` | 4 bytes |
| `I64` | tdsTypeI64 | `<q` | 8 bytes |
| `U8` | tdsTypeU8 | `<B` | 1 byte |
| `U16` | tdsTypeU16 | `<H` | 2 bytes |
| `U32` | tdsTypeU32 | `<I` | 4 bytes |
| `U64` | tdsTypeU64 | `<Q` | 8 bytes |
| `FLOAT32` | tdsTypeSingleFloat | `<f` | 4 bytes |
| `FLOAT64` | tdsTypeDoubleFloat | `<d` | 8 bytes |
| `BOOLEAN` | tdsTypeBoolean | `<B` | 1 byte |
| `STRING` | tdsTypeString | n/a | variable |
| `TIMESTAMP` | tdsTypeTimeStamp | `<qQ` | 16 bytes |

Timestamps use the NI epoch (1904-01-01 00:00:00 UTC). Offset from Unix epoch: `2 082 844 800` seconds.

## Running the tests

```bash
pip install "pytdms[test]"
pytest
```

## Project layout

```
pytdms/
├── pytdms/
│   ├── __init__.py        # Public exports
│   ├── constants.py       # DataType, ToC flags, VERSION, _TYPE_INFO
│   ├── encoder.py         # All binary serialisation — zero I/O
│   ├── channel.py         # Channel class, path escaping
│   ├── writer.py          # TdmsWriter (sync, seek-optimised)
│   └── async_writer.py    # AsyncTdmsWriter (aiofile, CPython only)
├── tests/
│   ├── conftest.py
│   ├── test_encoder.py
│   ├── test_writer.py
│   ├── test_nptdms_compat.py
│   └── test_async_writer.py
├── examples/
│   └── prepacked_data.py
└── pyproject.toml
```

## Limitations

- Little-endian output only (`kTocBigEndian` is not implemented)
- DAQmx raw data (format-changing scalers) is not supported
- Extended float (`tdsTypeExtendedFloat`) is not supported
- No `.tdms_index` sidecar file is written (NI tools auto-generate it on first open)
- Interleaved data layout (`kTocInterleavedData`) is not written (contiguous layout is always used; both are valid per spec)
