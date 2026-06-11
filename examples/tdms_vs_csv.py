import pytdms
import board
import busio
import sdcardio
import storage
import time
import struct

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
with pytdms.TdmsWriter('/sd/contiguous.tdms') as f:
    i_chan = pytdms.Channel("Simulated","Sample #", pytdms.DataType.I32)
    t_chan = pytdms.Channel("Simulated","Seconds", pytdms.DataType.FLOAT32)
    t0 = time.monotonic()
    for i in range(n//k):
        data = [(i, time.monotonic()-t0) for i in range(k)]
        indexes, times = zip(*data)
        f.write_segment([
            (i_chan, indexes),
            (t_chan, times)
            ])
print(f'Wrote {n} contiguous TDMS samples in {time.monotonic()-t0} seconds')

with pytdms.TdmsWriter('/sd/interleaved.tdms') as f:
    i_chan = pytdms.Channel("Simulated","Sample #", pytdms.DataType.I32)
    t_chan = pytdms.Channel("Simulated","Seconds", pytdms.DataType.FLOAT32)
    t0 = time.monotonic()
    for batch in range(n//k):
        # Create interleaved scan order: [ch0_s0][ch1_s0][ch0_s1][ch1_s1]...
        scans = b''.join([struct.pack("<if", sample, time.monotonic()-t0) for sample in range(k)])
        f.write_interleaved_segment([i_chan, t_chan], scans)
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