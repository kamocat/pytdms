"""
pytdms — Pure-Python streaming TDMS writer.

Public API
----------
``Channel``         — describes a TDMS channel (group, name, data type, properties)
``DataType``        — integer constants for all supported TDMS data types
``ToC``             — Table-of-Contents bitmask constants
``TdmsWriter``      — synchronous streaming writer (CircuitPython compatible)
``AsyncTdmsWriter`` — asynchronous writer (CPython + aiofile only; imported lazily)
"""

from pytdms.constants import DataType, ToC
from pytdms.channel import Channel
from pytdms.writer import TdmsWriter

def _lazy_async():
    from pytdms.async_writer import AsyncTdmsWriter
    return AsyncTdmsWriter

__all__ = [
    "DataType",
    "ToC",
    "Channel",
    "TdmsWriter",
]
