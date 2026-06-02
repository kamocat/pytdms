"""
pytdms.channel
==============
Channel and path helpers.

CircuitPython 10.x compatible — no ``dataclasses``, no ``typing``.
"""

from pytdms.constants import _RAW_DATA_TYPES

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _escape_name(name):
    """Replace every ``'`` with ``''`` per the TDMS path-escaping rules."""
    return name.replace("'", "''")


def file_object_path():
    """Return the TDMS path for the file-level object: ``/``."""
    return "/"


def group_path(group):
    """Return the TDMS path for a group object: ``/'group_name'``."""
    return "/'" + _escape_name(group) + "'"


def channel_path(group, name):
    """Return the TDMS path for a channel object: ``/'group'/'channel'``."""
    return "/'" + _escape_name(group) + "'/'" + _escape_name(name) + "'"


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class Channel:
    """Describes a TDMS channel (its location, type, and optional properties).

    Parameters
    ----------
    group :      str  — TDMS group name
    name :       str  — channel name within the group
    data_type :  int  — one of the ``DataType`` class attributes
    properties : dict | None
        Mapping of ``property_name -> (data_type_int, value)``.
        Can be populated later via ``add_property``.

    Notes
    -----
    A ``Channel`` object does **not** store raw sample data — data is passed
    to ``TdmsWriter.write_segment`` alongside the ``Channel`` instance.
    """

    __slots__ = ("group", "name", "data_type", "path", "properties")

    def __init__(self, group, name, data_type, properties=None):
        if data_type not in _RAW_DATA_TYPES:
            raise ValueError("data_type %d is not a supported raw-data type" % data_type)
        self.group = group
        self.name = name
        self.data_type = data_type
        self.path = channel_path(group, name)
        # properties: {name: (data_type_int, value)}
        self.properties = dict(properties) if properties else {}

    def add_property(self, name, data_type, value):
        """Add or overwrite a property on this channel.

        Parameters
        ----------
        name :      str  — property name
        data_type : int  — ``DataType`` value for the property
        value :          — Python value matching *data_type*
        """
        self.properties[name] = (data_type, value)

    def __repr__(self):
        return "Channel(group=%r, name=%r, data_type=%d)" % (self.group, self.name, self.data_type)
