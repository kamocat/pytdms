import struct
import array

try:
    from timeit import timeit
    import numpy as np
except ImportError:
    def timeit(func, number=1000):
        import time
        start = time.monotonic()
        for _ in range(number):
            func()
        return time.monotonic() - start
    import ulab.numpy as np

n = 100

def join_comprehension():
    # List comprehension
    return b''.join([struct.pack("<i", i) for i in range(n)])

def join_iterator():
    # Iterator
    a = (struct.pack("<i", i) for i in range(n))
    return b''.join(a)

def array_iterator():
    return array.array('l', range(n))

def array_float():
    return array.array('f', range(n))

def array_double():
    return array.array('d', range(n))

def array_list():
    a = list(range(n))
    return array.array('l', a)

def append_iterator():
    a = bytearray()
    for i in range(n):
        a.extend(struct.pack("<i", i))
    return a

def np_float():
    #Not sure yet how to get to the binary data
    return np.array(range(n))

if __name__ == '__main__':
    functions = [
        ('join_comprehension', join_comprehension),
        ('join_iterator', join_iterator),
        ('array_iterator', array_iterator),
        ('array_float', array_float),
        ('array_double', array_double),
        ('array_list', array_list),
        ('append_iterator', append_iterator),
        ('np_float', np_float),
    ]
    
    for name, func in functions:
        time = timeit(func, number=1000)
        print(f"{name}: {time:.4f} seconds")

### Results on RP2350
'''
join_comprehension: 1.9408 seconds
join_iterator: 2.1211 seconds
array_iterator: 0.2284 seconds
array_float: 0.1940 seconds
array_double: 0.2930 seconds
array_list: 0.4563 seconds
append_iterator: 2.1965 seconds
np_float: 0.2090 seconds
'''
