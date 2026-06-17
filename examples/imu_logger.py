import array
import os
import struct
import time

import adafruit_mpu6050
import board
import busio
import sdcardio
import storage
from adafruit_pcf8523.pcf8523 import PCF8523
from tdms import Channel, DataType
from tdms.constants import timestamp_from_datetime, _NI_EPOCH_OFFSET_SECONDS
from tdms.generator import TdmsSegmentGenerator

I2C = busio.I2C(board.GP5, board.GP4)
rtc = PCF8523(I2C)
mpu = adafruit_mpu6050.MPU6050(I2C, address=0x69)

## Configure the MPU6050
mpu.accelerometer_range = adafruit_mpu6050.Range.RANGE_2_G
mpu.gyro_range = adafruit_mpu6050.GyroRange.RANGE_250_DPS
mpu.sample_rate_divisor = 9  # ~100 Hz output (1000 / (1 + 9))
mpu.filter_bandwidth = adafruit_mpu6050.Bandwidth.BAND_94_HZ
mpu.fifo_en = True  # Enable FIFO
mpu.accel_fifo_en = True  # Enable accelerometer data in FIFO
mpu.gyro_fifo_en = True   # Enable gyroscope data in FIFO
sample_rate = 100  # Hz
gyro_range = 250  # degrees per second
accel_range = 2  # g

def struct_time_to_ni_timestamp(st):
    """Convert struct_time to NI TDMS timestamp tuple."""
    unix_seconds = int(time.mktime(st))
    ni_seconds = unix_seconds + _NI_EPOCH_OFFSET_SECONDS
    return (ni_seconds, 0)

def mpu_tdms():
    channels = [Channel("Acceleration", "X", DataType.I16),
            Channel("Acceleration", "Y", DataType.I16),
            Channel("Acceleration", "Z", DataType.I16),
            Channel("Gyroscope", "X", DataType.I16),
            Channel("Gyroscope", "Y", DataType.I16),
            Channel("Gyroscope", "Z", DataType.I16),]
    
    # Scaling factors per group
    scaling = {
        "Acceleration": (accel_range / 32768) * 9.80665,  # m/s² per full scale
        "Gyroscope": (gyro_range / 32768),  # °/s per full scale
    }
    
    # Add properties to each channel
    wf_start_time = struct_time_to_ni_timestamp(rtc.datetime)
    wf_increment = 1.0 / sample_rate
    for channel in channels:
        channel.add_property("wf_start_time", DataType.TIMESTAMP, wf_start_time)
        channel.add_property("wf_increment", DataType.FLOAT64, wf_increment)
        channel.add_property("slope", DataType.FLOAT64, scaling[channel.group])
        channel.add_property("intercept", DataType.FLOAT64, 0.0)
    
    return TdmsSegmentGenerator(channels, file_properties=None)

_spi = busio.SPI(MISO=board.GP16, clock=board.GP18, MOSI=board.GP19)
_sd = sdcardio.SDCard(_spi, board.GP17)  # change SD_CS to match your board
storage.mount(storage.VfsFat(_sd), "/sd")
dir = "/sd/"

# Format filename using struct_time from RTC
now = rtc.datetime
fname = dir + "{:04d}{:02d}{:02d}T{:02d}{:02d}{:02d}".format(
    now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min, now.tm_sec
) + '-imu.tdms'

with open(fname, 'wb') as f:
    t = time.mktime(now)
    os.utime(fname, (t, t))  # Set file timestamp to RTC time
    gen = mpu_tdms()
    k = 32  #Because we have interleaved data, this number probably doesn't matter
    header = gen.build_metadata(k, interleaved=True, big_endian=True)
    print(f'Header is {len(header)} bytes')
    f.write(header)
    d = 0
    mpu.read_whole_fifo()
    end = time.monotonic() + 5 # Log for 5 seconds
    while time.monotonic() < end:
        c = mpu.fifo_count
        if c > 0:
            d += c
            fifo_data = mpu.read_whole_fifo()
            if fifo_data:
                f.write(fifo_data)
        elif d>0:
            f.flush()
            print(f'Wrote {d} samples')
            d = 0
    print(f'Wrote {d} samples')