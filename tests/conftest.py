"""Shared fixtures and helpers for the pytdms test suite."""

import io

import pytest

try:
    import nptdms

    HAS_NPTDMS = True
except ImportError:
    HAS_NPTDMS = False

requires_nptdms = pytest.mark.skipif(not HAS_NPTDMS, reason="nptdms not installed")


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def read_tdms(path):
    """Read a TDMS file with nptdms and return the TdmsFile object."""
    return nptdms.TdmsFile.read(str(path))


def channel_data(path, group, name):
    """Read all data for a channel as a numpy array via nptdms."""
    return read_tdms(path)[group][name][:]


def channel_properties(path, group, name):
    """Return the properties dict for a channel via nptdms."""
    return read_tdms(path)[group][name].properties


def file_properties(path):
    """Return the file-level properties dict via nptdms."""
    return read_tdms(path).properties


# ---------------------------------------------------------------------------
# In-memory file factory (no disk I/O, for fast unit tests)
# ---------------------------------------------------------------------------


class SeekableBytesIO(io.BytesIO):
    """BytesIO that reports itself as seekable (it always is)."""

    pass


def make_mem_writer():
    """Return a (TdmsWriter, SeekableBytesIO) pair writing to memory."""
    from pytdms.writer import TdmsWriter

    buf = SeekableBytesIO()
    writer = TdmsWriter(buf)
    return writer, buf
