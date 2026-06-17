# tdms

Minimal TDMS segment generator for fixed interleaved data. CircuitPython 10.x compatible, zero dependencies.

## Features

- **Minimal API** — Single method: `build_metadata(num_scans, interleaved=True, big_endian=False)` returns lead-in + metadata bytes
- **Fixed channels** — Channel layout defined at initialization; no dynamic changes
- **Flexible data layout** — Supports both interleaved and contiguous data layouts
- **Full data-type support** — I8/16/32/64, U8/16/32/64, FLOAT32, FLOAT64, BOOLEAN, STRING, TIMESTAMP
- **CircuitPython 10.x compatible** — no `enum`, no `asyncio`, no `dataclasses`; only `struct` + `bytearray`
- **TDMS format verified** — 69 tests; 3 tests confirm output readable by nptdms library

## Installation

```bash
pip install tdms

# With test dependencies
pip install "tdms[test]"
```

For CircuitPython: copy the `tdms/` folder to your `CIRCUITPY/lib/` directory.

## Quick start

```python
from tdms import Channel, DataType, TdmsSegmentGenerator
import struct

# Define fixed channel layout (immutable after init)
ch_id = Channel("Sensors", "Sample#", DataType.I32)
ch_time = Channel("Sensors", "Seconds", DataType.FLOAT32)

gen = TdmsSegmentGenerator([ch_id, ch_time])

# Generate header: lead-in + metadata
header = gen.build_metadata(num_scans=64)

# You handle all file I/O
with open("data.tdms", "wb") as f:
    f.write(header)
    
    # Write 64 interleaved scans: [id][time][id][time]...[id][time]
    for i in range(64):
        f.write(struct.pack("<if", i, float(i) * 0.1))
```

## Interleaved data layout

Data is always interleaved per scan:

```
[ch0_scan0][ch1_scan0][ch2_scan0]  [ch0_scan1][ch1_scan1][ch2_scan1]  ...
```

For channels: I32 (4 bytes), F32 (4 bytes), F64 (8 bytes):
- Scan size: 16 bytes
- 64 scans: 1024 bytes raw data
- Header size: ~100 bytes (depends on group/channel names)
```

## File properties

Optional file-level properties are passed at initialization:

```python
from tdms import Channel, DataType, TdmsSegmentGenerator

ch = Channel("Data", "Value", DataType.F64)
props = {
    "Author": (DataType.STRING, "Alice"),
    "Description": (DataType.STRING, "Bench test"),
}

gen = TdmsSegmentGenerator([ch], file_properties=props)
header = gen.build_metadata(100)
```

## TDMS object hierarchy

| Object | Path format | Created by |
|--------|-------------|------------|
| File   | `/`         | Automatically in lead-in/metadata |
| Group  | `/'name'`   | Automatically when channel added |
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
pip install "tdms[test]"
pytest
```

Expected output: **69 passed** — 55 encoder + 14 generator + 3 nptdms validation

## Project layout

```
pytdms/
├── tdms/
│   ├── __init__.py        # Public exports: Channel, DataType, TdmsSegmentGenerator
│   ├── constants.py       # DataType, ToC flags, VERSION, _TYPE_INFO
│   ├── encoder.py         # Low-level binary packing functions
│   ├── channel.py         # Channel class, path escaping
│   └── generator.py       # TdmsSegmentGenerator (metadata generation)
├── tests/
│   ├── conftest.py
│   ├── test_encoder.py    # 55 encoder tests
│   └── test_generator.py  # 14 generator tests (including 3 nptdms validation)
├── examples/
│   ├── imu_logger.py      # A full example to show a real-world application of high-speed data logging
│   ├── tdms_vs_csv.py     # Shows teh actual performance benefits of using TDMS
│   ├── binpack.py         # Demonstrates the different methods for packign binary data and their relative performance
│   └── benchmark_results.md
├── utils/
│   ├── inspect.py         # Read and display TDMS file structure via nptdms
│   └── plot.py            # Visualize TDMS data with matplotlib
├── LICENSE
├── pyproject.toml
└── README.md
```

## Limitations & Design

- **Fixed channels** — Layout determined at init; no changes allowed
- **No I/O** — Library generates metadata only; caller handles file writing
- Extended float and DAQmx raw data not supported
- No `.tdms_index` sidecar files generated (nptdms auto-generates on first open)
