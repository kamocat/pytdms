"""
tdms.generator
================
Minimal TDMS segment header generation (I/O-free, interleaved data only).

Users provide fixed channels at initialization, then call build_metadata(num_scans) to get
lead-in + metadata bytes. You handle all writing.

CircuitPython 10.x compatible — no ``asyncio``, no ``typing``, no walrus operator,
no ``pathlib``.
"""

import struct

from tdms.channel import file_object_path, group_path
from tdms.constants import TOC_DEFAULT_INTERLEAVED, _TYPE_INFO
from tdms.encoder import (
    pack_lead_in,
    pack_no_data_index,
    pack_object_meta,
    pack_raw_index,
)


class TdmsSegmentGenerator:
    """Generate TDMS segment headers for fixed interleaved data layout.

    Initialize with channels once, then call build_metadata(num_scans) repeatedly.
    No file I/O, no dynamic layout changes.

    Parameters
    ----------
    channels : list of Channel
        Ordered list of channels in scan layout:
        ``[ch0_sample][ch1_sample]...[chN_sample]`` repeated per scan.
        **Fixed at initialization — no changes allowed.**
    file_properties : dict | None
        File-level properties (default: None).

    Examples
    --------
    ::

        import struct
        from tdms import Channel, DataType
        from tdms.generator import TdmsSegmentGenerator

        ch_id = Channel("Sensors", "Sample #", DataType.I32)
        ch_time = Channel("Sensors", "Seconds", DataType.FLOAT32)
        
        gen = TdmsSegmentGenerator([ch_id, ch_time], file_properties={})

        with open("output.tdms", "wb") as f:
            for batch in range(100):
                # Create 64 interleaved scans (8 bytes each)
                scans = b''.join([
                    struct.pack("<if", batch*64+i, time.time())
                    for i in range(64)
                ])
                
                header = gen.build_metadata(64)
                f.write(header + scans)
    """

    def __init__(self, channels, file_properties=None):
        """Initialize generator with fixed channel layout.

        Parameters
        ----------
        channels : list of Channel
            Ordered channel list (immutable after this).
        file_properties : dict | None
            ``{name: (data_type_int, value)}`` or None.
        """
        if not channels:
            raise ValueError("channels list cannot be empty")

        self._channels = channels
        self._file_properties = file_properties
        
        # Pre-calculate scan size (sum of all channel type sizes)
        self._scan_size = sum(_TYPE_INFO[ch.data_type][1] for ch in channels)

    def build_metadata(self, num_scans):
        """Build segment lead-in and metadata.
        
        Parameters
        ----------
        num_scans : int
            Number of interleaved scans in the segment.

        Returns
        -------
        bytes
            Lead-in + metadata bytes (write this, then raw scans).
        """
        metadata = self._build_segment_metadata(num_scans)
        raw_data_size = num_scans * self._scan_size
        next_segment_offset = len(metadata) + raw_data_size
        lead_in = pack_lead_in(TOC_DEFAULT_INTERLEAVED, next_segment_offset, len(metadata))
        return bytes(lead_in + metadata)

    def _build_segment_metadata(self, num_scans):
        """Build segment metadata for the fixed channel layout.

        Parameters
        ----------
        num_scans : int
            Number of samples per channel in this segment.

        Returns
        -------
        bytes
            Complete metadata section.
        """
        objects = []
        written_groups = set()

        # File object
        fp = list(self._file_properties.items()) if self._file_properties else []
        file_props_triples = [(n, dt, v) for n, (dt, v) in fp]
        objects.append(
            pack_object_meta(file_object_path(), pack_no_data_index(), file_props_triples)
        )

        # Groups
        for ch in self._channels:
            gp = group_path(ch.group)
            if gp not in written_groups:
                written_groups.add(gp)
                objects.append(pack_object_meta(gp, pack_no_data_index(), None))

        # Channels
        for ch in self._channels:
            index = pack_raw_index(ch.data_type, num_scans, None)
            prop_triples = [(n, dt, v) for n, (dt, v) in ch.properties.items()]
            objects.append(pack_object_meta(ch.path, index, prop_triples))

        # Pack all objects
        meta = bytearray(struct.pack("<I", len(objects)))
        for obj in objects:
            meta += obj
        return bytes(meta)
