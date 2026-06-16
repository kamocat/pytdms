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

n = 128

### 1D methods ###
data = list(range(n))

def join_iterator():
    # Iterator
    a = (struct.pack("<if", i, i*i) for i in range(n))
    return b''.join(a)

def struct_int32(fmt=f'<{n}i'): #Default argument pre-computes for format string
    return struct.pack(fmt, *range(n))
    
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

def np_float():
    return np.array(range(n)).tobytes()

def np_int():
    return np.array(range(n), dtype=np.int16).tobytes()

### 2D methods ###
data = list((i, i*i) for i in range(n))

#contiguous: n ints followed by n floats
def two_array():
    a,b = zip(*data)
    return array.array('i', a), array.array('f', b)

#Contiguous: n ints followed by n floats
def struct_mixed(fmt=f'<{n}i{n}f'): #Default argument pre-computes for format string
    a,b = zip(*data)
    return struct.pack(fmt, *(a+b))

#Interleaved ints and floats
def join_comprehension():
    # List comprehension
    return b''.join([struct.pack("<if", i, i*i) for i in range(n)])

#Interleaved ints and floats
def bytearray_loop():
    a = bytearray()
    for i in range(n):
        a.extend(struct.pack("<if", i,i*i))
    return a

#Interleaved ints and floats
def bytearray_prealloc():
    a = bytearray(n * 8)  # Preallocate for 100 int-float pairs
    for i in range(n):
        struct.pack_into("<if", a, i*8, i, i*i)
    return a

def np_2d():
    return np.array(data).tobytes()

#What order are the numpy arrays stored in?
def determine_byte_order():
    a = np.array([[1,2],[3,4]]).tobytes() #ulab.numpy does not support doubles
    b = struct.unpack('<4f', a)
    if b[3] > b[2]:
        print("Numpy arrays are stored in contiguous order (row-major)")
    else:
        print("Numpy arrays are stored in interleaved order (column-major)")

def main():
    functions = [
        #('array.array int8', array_int8),
        #('array.array int16', array_int16),
        ('array.array int32', array_int32),
        #('array.array int64', array_int64),
        ('array.array float', array_float),
        ('array.array double', array_double),
        ('array.array from list', array_list),
        ('numpy.array float', np_float),
        ('numpy.array int', np_int),
        ('struct.pack int32', struct_int32),
        ('two arrays', two_array),
        ('numpy.array 2dims', np_2d),
        ('struct.pack mixed', struct_mixed),
        ('b"".join comprehension', join_comprehension),
        ('b"".join iterator', join_iterator),
        ('bytearray.extend loop', bytearray_loop),
        ('bytearray preallocate', bytearray_prealloc),
    ]
    print("Benchmark\t\tTime (ms)")
    for name, func in functions:
        time = timeit(func, number=1000) * 1000
        print(f"{name}\t{time:.4f}")
    determine_byte_order()

main()