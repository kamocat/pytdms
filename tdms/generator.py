"""
tdms.generator
================
Minimal TDMS segment header generation (I/O-free, interleaved or non-interleaved data).

Users provide fixed channels at initialization, then call build_metadata(num_scans) to get
lead-in + metadata bytes. You handle all writing.

CircuitPython 10.x compatible — no ``asyncio``, no ``typing``, no walrus operator,
no ``pathlib``.
"""

import struct

from tdms.channel import file_object_path, group_path
from tdms.constants import (
    ToC,
    _TYPE_INFO,
)
from tdms.encoder import (
    pack_lead_in,
    pack_no_data_index,
    pack_object_meta,
    pack_raw_index,
)


class TdmsSegmentGenerator:
    """Generate TDMS segment headers for fixed data layout (interleaved or non-interleaved).

    Initialize with channels once, then call build_metadata(num_scans) repeatedly.
    No file I/O, no dynamic layout changes.

    Parameters
    ----------
    channels : list of Channel
        Ordered list of channels in scan layout.
        
        **Interleaved layout** (when interleaved=True in build_metadata):
            ``[ch0_sample][ch1_sample]...[chN_sample]`` repeated per scan.
        
        **Non-interleaved layout** (when interleaved=False in build_metadata):
            All samples of ch0, then all samples of ch1, etc.
            ``[ch0_sample][ch0_sample]...[ch1_sample][ch1_sample]...``
        
        **Fixed at initialization — no changes allowed.**
    
    file_properties : dict | None
        File-level properties (default: None).

    Examples
    --------
    **Interleaved layout:**
    
    ::

        import struct
        from tdms import Channel, DataType
        from tdms.generator import TdmsSegmentGenerator

        ch_id = Channel("Sensors", "Sample #", DataType.I32)
        ch_time = Channel("Sensors", "Seconds", DataType.FLOAT32)
        
        gen = TdmsSegmentGenerator([ch_id, ch_time], file_properties={})

        with open("interleaved.tdms", "wb") as f:
            for batch in range(100):
                # Create 64 interleaved scans: [id0,time0,id1,time1,...]
                scans = b''.join([
                    struct.pack("<if", batch*64+i, time.time())
                    for i in range(64)
                ])
                
                header = gen.build_metadata(64, interleaved=True)
                f.write(header + scans)
    
    **Non-interleaved layout:**
    
    ::

        with open("non_interleaved.tdms", "wb") as f:
            for batch in range(100):
                # All id values first, then all time values
                ids = b''.join([struct.pack("<i", batch*64+i) for i in range(64)])
                times = b''.join([struct.pack("<f", time.time()) for i in range(64)])
                scans = ids + times
                
                header = gen.build_metadata(64, interleaved=False)
                f.write(header + scans)
    
    **Big-endian metadata:**
    
    ::

        gen = TdmsSegmentGenerator([ch_id, ch_time], file_properties={})
        
        with open("big_endian.tdms", "wb") as f:
            for batch in range(100):
                scans = b''.join([
                    struct.pack(">if", batch*64+i, time.time())
                    for i in range(64)
                ])
                
                header = gen.build_metadata(64, big_endian=True)
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

    def build_metadata(self, num_scans, interleaved=False, big_endian=False):
        """Build segment lead-in and metadata.

        Parameters
        ----------
        num_scans : int
            Number of scans (interleaved) or samples per channel (non-interleaved)
            in the segment.
        interleaved : bool
            If True, use interleaved data layout. If False (default), use
            non-interleaved (contiguous per-channel) layout.
        big_endian : bool
            If False (default), all numeric values use little-endian byte order.
            If True, all numeric values use big-endian byte order. This includes
            the lead-in, metadata, and raw data.

        Returns
        -------
        bytes
            Lead-in + metadata bytes (write this, then raw scans).
        """
        metadata = self._build_segment_metadata(num_scans, big_endian=big_endian)

        # Select ToC based on interleaved and big_endian settings
        toc = ToC.META | ToC.NEW_OBJ_LIST | ToC.RAW
        if interleaved:
            toc |= ToC.INTERLEAVED
        if big_endian:
            toc |= ToC.BIG_ENDIAN

        # If the value of Next segment offset is -1, the raw data size of total chunks
        # equals the file size minus the absolute beginning position of the raw data.
        # It allows us to append data without updating the header.
        next_segment_offset = -1
        # NOTE: Lead-in is always little-endian per TDMS spec, regardless of big_endian flag
        lead_in = pack_lead_in(toc, next_segment_offset, len(metadata), big_endian=False)
        return bytes(lead_in + metadata)

    def _build_segment_metadata(self, num_scans, big_endian=False):
        """Build segment metadata for the fixed channel layout.

        Parameters
        ----------
        num_scans : int
            Number of samples per channel in this segment.
        big_endian : bool
            If True, use big-endian format for all numeric fields.

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
            pack_object_meta(file_object_path(), pack_no_data_index(), file_props_triples, big_endian=big_endian)
        )

        # Groups
        for ch in self._channels:
            gp = group_path(ch.group)
            if gp not in written_groups:
                written_groups.add(gp)
                objects.append(pack_object_meta(gp, pack_no_data_index(), None, big_endian=big_endian))

        # Channels
        for ch in self._channels:
            index = pack_raw_index(ch.data_type, num_scans, None, big_endian=big_endian)
            prop_triples = [(n, dt, v) for n, (dt, v) in ch.properties.items()]
            objects.append(pack_object_meta(ch.path, index, prop_triples, big_endian=big_endian))

        # Pack all objects
        fmt = ">I" if big_endian else "<I"
        meta = bytearray(struct.pack(fmt, len(objects)))
        for obj in objects:
            meta += obj
        return bytes(meta)
