import os
import time

import adafruit_mpu6050
import board
import busio
import sdcardio
import storage
from adafruit_pcf8523.pcf8523 import PCF8523

from tdms import Channel, DataType, TdmsSegmentGenerator
from tdms.constants import _NI_EPOCH_OFFSET_SECONDS

I2C = busio.I2C(board.GP5, board.GP4)
rtc = PCF8523(I2C)
mpu = adafruit_mpu6050.MPU6050(I2C, address=0x69)

def set_fifo_enables(mpu, enable_accel=True, enable_gyro=True, enable_temp=False):
    fifo_en_byte = 0x00 
    if enable_accel:
        fifo_en_byte |= (1 << 3)
    if enable_gyro:
        fifo_en_byte |= (7 << 4)
    if enable_temp:
        fifo_en_byte |= (1 << 7)
    # Write directly to FIFO_EN register
    with mpu.i2c_device:
        mpu.i2c_device.write(bytes([0x23, fifo_en_byte]))

    # Enable FIFO mode in USER_CTRL register (0x6A, bit 6)
    with mpu.i2c_device:
        # Read current USER_CTRL value
        mpu.i2c_device.write(bytes([0x6A]))
        user_ctrl = bytearray(1)
        mpu.i2c_device.readinto(user_ctrl)
        # Set bit 6 (FIFO_EN)
        user_ctrl[0] |= (1 << 6)
        # Write back
        mpu.i2c_device.write(bytes([0x6A, user_ctrl[0]]))

## Configure the MPU6050
mpu.accelerometer_range = adafruit_mpu6050.Range.RANGE_2_G
mpu.gyro_range = adafruit_mpu6050.GyroRange.RANGE_250_DPS
mpu.sample_rate_divisor = 15  # ~500 Hz output
set_fifo_enables(mpu, enable_accel=True, enable_gyro=True, enable_temp=False)
sample_rate = 500  # Hz
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

d2 = 0
start = time.monotonic()
try:
    with open(fname, 'wb') as f:
        t = time.mktime(now)
        os.utime(fname, (t, t))  # Set file timestamp to RTC time
        gen = mpu_tdms()
        k = 1  #Because we have interleaved data, this number probably doesn't matter
        header = gen.build_metadata(k, interleaved=True, big_endian=True)
        print(f'Header is {len(header)} bytes')
        f.write(header)
        mpu.read_whole_fifo()
        start = time.monotonic()
        end = start + 5 # Log for 5 seconds
        d = 0
        while time.monotonic() < end:
            c = mpu.fifo_count
            if c > 0:
                d += c
                fifo_data = mpu.read_whole_fifo()
                if fifo_data:
                    f.write(fifo_data)
                d2 += c
            elif d>0:
                f.flush()
                print(f'Wrote {d} bytes')
                d = 0
except Exception as e:
    print(e)
finally:
    print(f'Wrote {d2//12} samples in {time.monotonic()-start:0.1f} seconds')
