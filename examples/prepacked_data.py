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

imu_raw: bytes = struct.pack(
    "<BhhhhhhbH", 0xC0, 100, -100, 50, 1, -1, 2, 25, 1500
)  # IMU packet: header + accel + gyro + temperature + microseconds

ch_hdr = Channel("IMU", "Header", DataType.U8)
ch_ax = Channel("IMU", "Accel_X", DataType.I16)
ch_ay = Channel("IMU", "Accel_Y", DataType.I16)
ch_az = Channel("IMU", "Accel_Z", DataType.I16)
ch_gx = Channel("IMU", "Gyro_X", DataType.I16)
ch_gy = Channel("IMU", "Gyro_Y", DataType.I16)
ch_gz = Channel("IMU", "Gyro_Z", DataType.I16)
ch_temp = Channel("IMU", "Temperature", DataType.I8)
ch_us = Channel("IMU", "Microseconds", DataType.U16)
channels = [ch_hdr, ch_ax, ch_ay, ch_az, ch_gx, ch_gy, ch_gz, ch_temp, ch_us]

# ---------------------------------------------------------------------------
# Scaling properties — NI DAQmx linear-scale convention.
# nptdms and LabVIEW apply these automatically on read-back.
#
# I16 full range = 65536 counts over the full span.
#   Accel ±2 g  → slope = 4 / 65536 g/count
#   Gyro ±250 °/s → slope = 500 / 65536 (°/s)/count
# ---------------------------------------------------------------------------
_ACCEL_SLOPE = 4.0 / 65536.0  # g per count
_GYRO_SLOPE = 500.0 / 65536.0  # deg/s per count


def _add_linear_scale(ch, slope, unit, intercept=0.0):
    ch.add_property("NI_Scale[0]_Scale_Type", DataType.STRING, "Linear")
    ch.add_property("NI_Scale[0]_Linear_Slope", DataType.FLOAT64, slope)
    ch.add_property("NI_Scale[0]_Linear_Y_Intercept", DataType.FLOAT64, intercept)
    ch.add_property("NI_Scale[0]_Input_Source", DataType.STRING, "DAQmx_Raw_Data")
    ch.add_property("NI_Scaling_Status", DataType.STRING, "Scaled")
    ch.add_property("unit_string", DataType.STRING, unit)


for _ch in (ch_ax, ch_ay, ch_az):
    _add_linear_scale(_ch, _ACCEL_SLOPE, "g")

for _ch in (ch_gx, ch_gy, ch_gz):
    _add_linear_scale(_ch, _GYRO_SLOPE, "deg/s")

_add_linear_scale(ch_temp, 1 / 2.07, "°C", 25)
_add_linear_scale(ch_us, 1.0, "µs")

n = 101
# Concatenate 32 copies to simulate a DMA ring-buffer flush
buf_32 = imu_raw * n

if True:  # simulate data using random walk
    import numpy as np

    d_header = 0x68
    d_ax = np.cumsum(np.random.normal(0, 10, n)).astype(np.int16)
    d_ay = np.cumsum(np.random.normal(0, 10, n)).astype(np.int16)
    d_az = (16556 + np.cumsum(np.random.normal(0, 10, n))).astype(np.int16)
    d_gx = np.cumsum(np.random.normal(0, 5, n)).astype(np.int16)
    d_gy = np.cumsum(np.random.normal(0, 20, n)).astype(np.int16)
    d_gz = np.cumsum(np.random.normal(0, 50, n)).astype(np.int16)
    d_temp = np.cumsum(np.random.normal(25, 1, n)).astype(np.int8)
    d_us = np.linspace(0, 10_000, n).astype(np.uint16)
    buf_32 = b"".join(
        struct.pack(
            "<BhhhhhhbH",
            d_header,
            d_ax[i],
            d_ay[i],
            d_az[i],
            d_gx[i],
            d_gy[i],
            d_gz[i],
            d_temp[i],
            d_us[i],
        )
        for i in range(n)
    )

with TdmsWriter(OUTPUT_FILE) as writer:
    writer.write_interleaved_segment(channels, buf_32)

print("Written:", OUTPUT_FILE)

try:
    import nptdms

    tdms = nptdms.TdmsFile.read(OUTPUT_FILE)
    az = tdms["IMU"]["Accel_Z"][:]
    print("Accel_Z sample count :", len(az))
    print("Accel_Z first 5 vals :", az[:5].tolist())
    print("Microseconds  first 5 vals :", tdms["IMU"]["Microseconds"][:5].tolist())
except ImportError:
    print("(Install nptdms to verify: pip install nptdms)")
