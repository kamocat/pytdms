| Benchmark | ESP32-S3 | RP2040 | RP2350 |
|-----------|----------|--------|--------|
| array.array int32 | 0.2434 | 0.5760 | 0.3270 |
| array.array float | 0.2136 | 0.5420 | 0.2830 |
| array.array double | 0.5000 | 1.1720 | 0.7000 |
| array.array from list | 0.4790 | 1.1340 | 0.6680 |
| numpy.array float | 0.2383 | 0.5700 | 0.2930 |
| numpy.array int | 0.2239 | 0.5080 | 0.2640 |
| struct.pack int32 | 0.3269 | 0.8370 | 0.4760 |
| two arrays | 1.4441 | 3.3760 | 1.8580 |
| numpy.array 2dims | 0.7798 | 2.4630 | 1.0220 |
| struct.pack mixed | 0.9412 | 2.5610 | 3.1130 |
| b"".join comprehension | 2.0078 | 5.9730 | 3.7890 |
| b"".join iterator | 2.3047 | 5.3560 | 3.5170 |
| bytearray.extend loop | 2.4192 | 7.4330 | 4.2460 |
| bytearray preallocate | 1.4922 | 3.8940 | 2.1480 |

*Numpy arrays are stored in contiguous order (row-major)*