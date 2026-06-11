import board
import busio
import sdcardio
import storage
import time
import struct
from tdms import Channel, DataType
from tdms.generator import TdmsSegmentGenerator

_spi = busio.SPI(MISO=board.GP16, clock=board.GP18, MOSI=board.GP19)
_sd = sdcardio.SDCard(_spi, board.GP17)  # change SD_CS to match your board
storage.mount(storage.VfsFat(_sd), "/sd")


n = 1000
with open('/sd/test.csv', 'w') as f:
    f.write('Line, Time\n')
    t0 = time.monotonic()
    for i in range(n):
        f.write(f'{i},{time.monotonic()-t0}\n')
elapsed = time.monotonic() - t0

print(f'Wrote {n} csv lines in {elapsed} seconds')

k = 64

with open('/sd/interleaved.tdms', "wb") as f:
    # Fixed channels at initialization
    i_chan = Channel("Simulated", "Sample #", DataType.I32)
    t_chan = Channel("Simulated", "Seconds", DataType.FLOAT32)
    gen = TdmsSegmentGenerator([i_chan, t_chan], file_properties={})
    t0 = time.monotonic()
    header = gen.build_metadata(n)
    print(f'Header is {len(header)} bytes')
    f.write(header)
    for batch_idx in range(n // k):
        # Generate header (lead-in + metadata)
        scans = b''.join([struct.pack("<if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write(scans)
print(f'Wrote {n} interleaved TDMS samples in {time.monotonic()-t0} seconds')

with open('/sd/binary.blob', 'wb') as f:
    t0 = time.monotonic()
    for batch in range(n//k):
        # Create interleaved scan order: [ch0_s0][ch1_s0][ch0_s1][ch1_s1]...
        scans = b''.join([struct.pack("<if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write(scans)
print(f'Wrote {n} binary samples in {time.monotonic()-t0} seconds') 

s = f'{n},{time.monotonic()-t0}\n'
with open('/sd/dummy.txt', 'w') as f:
    t0 = time.monotonic()
    for i in range(n):
        f.write(s)
print(f'Wrote {n} dummy lines in {time.monotonic()-t0} seconds')