import struct
import array

try:
    from timeit import timeit
    import numpy as np
except ImportError:
    def timeit(func, number=1000):
        import time
        import gc
        gc.collect()
        start = time.monotonic()
        for _ in range(number):
            func()
        return (time.monotonic() - start)/number
    import ulab.numpy as np

n = 100

def join_comprehension():
    # List comprehension
    return b''.join([struct.pack("<if", i, i*i) for i in range(n)])

def join_iterator():
    # Iterator
    a = (struct.pack("<if", i, i*i) for i in range(n))
    return b''.join(a)

def struct_int32():
    return struct.pack(f'<{n}i', *range(n))

def struct_mixed():
    return struct.pack(f'<{n}i{n}f', *[x for i in range(n) for x in (i, i*i)])
    
def array_int8():
    return array.array('b', range(n))
    
def array_int16():
    return array.array('i', range(n))

def array_int32():
    return array.array('l', range(n))

def array_int64():
    return array.array('q', range(n))

def array_float():
    return array.array('f', range(n))

def array_double():
    return array.array('d', range(n))

def array_list():
    a = list(range(n))
    return array.array('l', a)

def bytearray_loop():
    a = bytearray()
    for i in range(n):
        a.extend(struct.pack("<if", i,i*i))
    return a

def np_float():
    return np.array(range(n)).tobytes()

def np_2d():
    return np.array([[i,i*i] for i in range(n)]).tobytes()

if __name__ == '__main__':
    functions = [
        ('array.array int8', array_int8),
        ('array.array int16', array_int16),
        ('array.array int32', array_int32),
        ('array.array int64', array_int64),
        ('array.array float', array_float),
        ('array.array double', array_double),
        ('array.array from list', array_list),
        ('numpy.array float', np_float),
        ('numpy.array 2dims', np_2d),
        ('struct.pack int32', struct_int32),
        ('struct.pack mixed', struct_mixed),
        ('b"".join comprehension', join_comprehension),
        ('b"".join iterator', join_iterator),
        ('bytearray.extend loop', bytearray_loop),
    ]
    print("Benchmark\t\tTime (ms)")
    for name, func in functions:
        time = timeit(func, number=1000) * 1000
        print(f"{name}\t{time:.4f}")

### Benchmark Results

Time to pack 100 numbers into bytes, in milliseconds (lower is better).
Results may vary based on the specific hardware and Python implementation used.

```
1D Benchmarks
Benchmark               | RP2350 | RP2040 | Feather M0 | ESP32-S3
------------------------|--------|--------|------------|----------
array.array int8        | 0.1640 | 0.3229 |   1.4370   | 0.1380
array.array int16       | 0.1960 | 0.3698 |   1.6810   | 0.1540
array.array int32       | 0.1960 | 0.3679 |   1.6820   | 0.1580
array.array int64       | 0.2440 | 0.4632 |   2.1710   | 0.1870
array.array float       | 0.1630 | 0.3431 |   1.4540   | 0.1270
array.array double      | 0.2200 | 0.4590 |   2.0460   | 0.1740
array.array from list   | 0.3930 | 0.6970 |   3.1130   | 0.2770
numpy.array float       | 0.1690 | 0.3682 |    N/A     | 0.1451
struct.pack int32       | 0.3990 | 0.7070 |   3.2010   | 0.3420

2D Benchmarks
Benchmark               | RP2350 | RP2040 | Feather M0 | ESP32-S3
------------------------|--------|--------|------------|----------
numpy.array 2dims       | 1.3550 | 2.5629 |    N/A     | 1.0012
struct.pack mixed       | 1.6360 | 2.9512 |  14.2220   | 1.2880
b"".join comprehension  | 2.2530 | 3.6461 |  16.2620   | 1.5220
b"".join iterator       | 2.4180 | 3.8978 |  17.5450   | 1.7810
bytearray.extend loop   | 2.7180 | 4.9160 |  20.3790   | 1.7700
```