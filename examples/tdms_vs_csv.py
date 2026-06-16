import time
import struct
import array
from tdms import Channel, DataType
from tdms.generator import TdmsSegmentGenerator

try:
    import board
    import busio
    import sdcardio
    import storage

    _spi = busio.SPI(MISO=board.GP16, clock=board.GP18, MOSI=board.GP19)
    _sd = sdcardio.SDCard(_spi, board.GP17)  # change SD_CS to match your board
    storage.mount(storage.VfsFat(_sd), "/sd")
    dir = "/sd/"
except ImportError:
    dir = "./"

n = 10000

with open(dir+'test.csv', 'w') as f:
    f.write('Line, Time\n')
    t0 = time.monotonic()
    for i in range(n):
        f.write(f'{i},{time.monotonic()-t0}\n')
elapsed = time.monotonic() - t0

print(f'Wrote {n} csv lines in {elapsed} seconds')

k = 64

with open(dir+'contiguous.tdms', 'wb') as f:
    # Channels are decided at initialization
    i_chan = Channel("Simulated", "Sample #", DataType.I32)
    t_chan = Channel("Simulated", "Seconds", DataType.FLOAT32)
    gen = TdmsSegmentGenerator([i_chan, t_chan], file_properties={})
    t0 = time.monotonic()
    header = gen.build_metadata(k)
    print(f'Header is {len(header)} bytes')
    f.write(header)
    for batch_idx in range(n // k):
        #TDMs allows us to store data in blocks, which is faster in some cases
        #In this instance it means the timestamps will be wrong, but it's fake data anyway
        times = array.array('f', [time.monotonic() for i in range(k)])
        samples = array.array('i', range(k))
        f.write(samples)
        f.write(times)
print(f'Wrote {n} contiguous TDMS samples in {time.monotonic()-t0} seconds')

with open(dir+'interleaved.tdms', 'wb') as f:
    i_chan = Channel("Simulated", "Sample #", DataType.I32)
    t_chan = Channel("Simulated", "Seconds", DataType.FLOAT32)
    gen = TdmsSegmentGenerator([i_chan, t_chan], file_properties={})
    t0 = time.monotonic()
    header = gen.build_metadata(k, interleaved=True)
    print(f'Header is {len(header)} bytes')
    f.write(header)
    for batch_idx in range(n // k):
        #Here the timestamps are correct, but array comprehension is expensive
        scans = b''.join([struct.pack("<if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write(scans)
print(f'Wrote {n} interleaved TDMS samples in {time.monotonic()-t0} seconds')

with open(dir+'big-endian.tdms', 'wb') as f:
    i_chan = Channel("Simulated", "Sample #", DataType.I32)
    t_chan = Channel("Simulated", "Seconds", DataType.FLOAT32)
    gen = TdmsSegmentGenerator([i_chan, t_chan], file_properties={})
    t0 = time.monotonic()
    header = gen.build_metadata(k, interleaved=True, big_endian=True)
    print(f'Header is {len(header)} bytes')
    f.write(header)
    for batch_idx in range(n // k):
        #Now we're swapping bytes for big-endian, which is even slower
        #You really only want to use this mode if you're logging raw sensor data
        #and it's already in big-endian format
        scans = b''.join([struct.pack(">if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write(scans)
print(f'Wrote {n} big-endian TDMS samples in {time.monotonic()-t0} seconds')

with open(dir+'binary.blob', 'wb') as f:
    t0 = time.monotonic()
    for batch in range(n//k):
        # Create interleaved scan order: [ch0_s0][ch1_s0][ch0_s1][ch1_s1]...
        scans = b''.join([struct.pack("<if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write(scans)
print(f'Wrote {n} binary samples in {time.monotonic()-t0} seconds') 

s = f'{n},{time.monotonic()-t0}\n'
with open(dir+'dummy.txt', 'w') as f:
    t0 = time.monotonic()
    for i in range(n):
        f.write(s)
print(f'Wrote {n} dummy lines in {time.monotonic()-t0} seconds')