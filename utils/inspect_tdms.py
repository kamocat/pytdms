"""Inspect TDMS file structure."""

from nptdms import TdmsFile
import glob

files = glob.glob("logs/*.tdms")

for fname in files:
    print(f"Inspecting {fname}...")
    tdms_file = TdmsFile(fname)

    print("Groups in file:")
    for group in tdms_file.groups():
        print(f"  Group: {group.name}")
        for channel in group.channels():
            print(f"    Channel: {channel.name} - {len(channel.data)} samples")
        print(f"    Properties: {group.properties}")
