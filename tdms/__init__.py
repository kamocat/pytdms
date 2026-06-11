"""
tdms — Minimal TDMS segment generator for fixed interleaved data.

Public API
----------
``Channel``              — describes a TDMS channel (group, name, data type, properties)
``DataType``             — integer constants for all supported TDMS data types
``ToC``                  — Table-of-Contents bitmask constants
``TdmsSegmentGenerator`` — metadata generator (fixed channels, interleaved data only)
"""

from tdms.channel import Channel
from tdms.constants import DataType, ToC
from tdms.generator import TdmsSegmentGenerator


__all__ = [
    "DataType",
    "ToC",
    "Channel",
    "TdmsSegmentGenerator",
]
