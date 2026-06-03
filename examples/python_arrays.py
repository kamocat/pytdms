"""
write_segment example — Python arrays
======================================
Use write_segment() when data is stored as Python lists or other iterables
of Python scalars.  The writer packs each channel's values in contiguous
(non-interleaved) order: all samples for channel 0, then all samples for
channel 1, etc.

This is the right path for:
  * Pure-Python sensor loops (no struct.pack required)
  * Logging data received one sample at a time into a list
  * Mixed-rate channels (not all channels update every tick)
  * Variable-length channels (e.g. strings)

The same-segment append optimisation applies: as long as the set of channels
and their types stay the same between calls, only raw bytes are appended and
the open segment is extended in-place.
"""

import random

from pytdms import Channel, DataType, TdmsWriter

OUTPUT_FILE = "python_arrays_output.tdms"

# ---------------------------------------------------------------------------
# Channel definitions
# ---------------------------------------------------------------------------
ch_temp = Channel("Environment", "Temperature_C", DataType.FLOAT32)
ch_pressure = Channel("Environment", "Pressure_hPa", DataType.FLOAT32)
ch_humidity = Channel("Environment", "Humidity_pct", DataType.FLOAT32)
ch_light = Channel("Environment", "Lux", DataType.FLOAT64)
ch_adc = Channel("Analog", "ADC_0", DataType.I16)
ch_counter = Channel("Analog", "Counter", DataType.U32)
ch_gate = Channel("Control", "Gate", DataType.BOOLEAN)

# File-level properties (written in the first segment lead-in)
file_props = {
    "author": (DataType.STRING, "pytdms example"),
    "description": (DataType.STRING, "Environmental sensor log"),
    "sample_rate_hz": (DataType.I32, 10),
}

# Channel properties are set on the Channel objects before writing
ch_temp.properties = {"unit": (DataType.STRING, "degC"), "sensor": (DataType.STRING, "SHT40")}
ch_pressure.properties = {"unit": (DataType.STRING, "hPa"), "sensor": (DataType.STRING, "BMP388")}
ch_humidity.properties = {"unit": (DataType.STRING, "%RH"), "sensor": (DataType.STRING, "SHT40")}
ch_light.properties = {"unit": (DataType.STRING, "lux"), "sensor": (DataType.STRING, "OPT3001")}
ch_adc.properties = {"unit": (DataType.STRING, "counts"), "resolution": (DataType.I32, 12)}
ch_counter.properties = {"unit": (DataType.STRING, "ticks")}
ch_gate.properties = {"description": (DataType.STRING, "acquisition gate")}


# All channels written together on every tick
ALL_CHANNELS = [
    ch_temp,
    ch_pressure,
    ch_humidity,
    ch_light,
    ch_adc,
    ch_counter,
    ch_gate,
]

# ---------------------------------------------------------------------------
# Simulate 100 samples, writing in batches of 10
# ---------------------------------------------------------------------------
TOTAL_SAMPLES = 100
BATCH_SIZE = 10
N_BATCHES = TOTAL_SAMPLES // BATCH_SIZE

random.seed(42)

with TdmsWriter(OUTPUT_FILE) as writer:
    for batch_idx in range(N_BATCHES):
        temps = [20.0 + random.gauss(0, 0.5) for _ in range(BATCH_SIZE)]
        pressures = [1013.0 + random.gauss(0, 2) for _ in range(BATCH_SIZE)]
        humidities = [50.0 + random.gauss(0, 1) for _ in range(BATCH_SIZE)]
        lux = [float(random.randint(0, 65000)) for _ in range(BATCH_SIZE)]
        adc = [random.randint(-2048, 2047) for _ in range(BATCH_SIZE)]
        counter = list(range(batch_idx * BATCH_SIZE, batch_idx * BATCH_SIZE + BATCH_SIZE))
        gate = [True] * BATCH_SIZE  # acquisition always open

        # First call writes the full segment (lead-in + metadata + raw data).
        # Subsequent calls with the same channel list reuse the open segment —
        # only the raw bytes are written (no metadata overhead).
        writer.write_segment(
            [
                (ch_temp, temps),
                (ch_pressure, pressures),
                (ch_humidity, humidities),
                (ch_light, lux),
                (ch_adc, adc),
                (ch_counter, counter),
                (ch_gate, gate),
            ],
            file_properties=file_props if batch_idx == 0 else None,
        )

print("Written:", OUTPUT_FILE)

# ---------------------------------------------------------------------------
# Part 2: Logging strings
# ---------------------------------------------------------------------------
# String channels hold variable-length UTF-8 text.  Because each write may
# produce a different number of raw bytes, string channels must be written in
# their own write_segment() call — they cannot share a segment with numeric
# channels (the same-segment append optimisation requires equal raw byte counts
# per chunk).
#
# Typical uses: alarm messages, state transitions, operator notes, CSV rows.
# ---------------------------------------------------------------------------

OUTPUT_FILE_EVENTS = "python_arrays_events.tdms"

ch_event_name = Channel("Events", "EventName", DataType.STRING)
ch_event_msg = Channel("Events", "Message", DataType.STRING)

# Each write_segment call logs one or more events.  A new TDMS segment is
# started for every call because string byte lengths vary between calls.
event_log = [
    ("STARTUP", "System initialised, sensors online"),
    ("ALARM", "Temperature exceeded threshold: 35.1 C"),
    ("ALARM", "Humidity out of range: 82.3 %RH"),
    ("INFO", "Calibration applied"),
    ("SHUTDOWN", "Orderly shutdown requested"),
]

with TdmsWriter(OUTPUT_FILE_EVENTS) as writer:
    for name, message in event_log:
        writer.write_segment(
            [
                (ch_event_name, [name]),
                (ch_event_msg, [message]),
            ]
        )

print("Written:", OUTPUT_FILE_EVENTS)

# ---------------------------------------------------------------------------
# Verify with nptdms (optional — requires: pip install nptdms)
# ---------------------------------------------------------------------------
try:
    import nptdms

    tdms = nptdms.TdmsFile.read(OUTPUT_FILE)
    print("Temperature sample count:", len(tdms["Environment"]["Temperature_C"][:]))
    print("Temperature first 5:", tdms["Environment"]["Temperature_C"][:5].tolist())
    print("Counter first 5    :", tdms["Analog"]["Counter"][:5].tolist())
    print("Gate first 5       :", tdms["Control"]["Gate"][:5].tolist())

    tdms_ev = nptdms.TdmsFile.read(OUTPUT_FILE_EVENTS)
    print("Event names:", tdms_ev["Events"]["EventName"][:].tolist())
    print("Messages   :", tdms_ev["Events"]["Message"][:].tolist())
except ImportError:
    print("(Install nptdms to verify: pip install nptdms)")
