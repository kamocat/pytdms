"""Plot IMU data from TDMS file using nptdms, extracting metadata dynamically."""

import matplotlib.pyplot as plt
from nptdms import TdmsFile
import glob

# Open the TDMS file
fname = glob.glob("logs/*.tdms")[0]
tdms_file = TdmsFile(fname)

# Extract groups and build data structure
groups_data = {}
wf_increment = None  # Sample period in seconds

for group in tdms_file.groups():
    group_name = group.name
    groups_data[group_name] = {"channels": {}, "units": "", "slope": None}
    
    for channel in group.channels():
        channel_name = channel.name
        raw_data = channel.data  # Use .data instead of .read()
        
        # Extract metadata
        slope = channel.properties.get("slope", 1.0)
        intercept = channel.properties.get("intercept", 0.0)
        if wf_increment is None and "wf_increment" in channel.properties:
            wf_increment = channel.properties.get("wf_increment", 0.01)
        
        # Scale the data: actual_value = raw_value * slope + intercept
        scaled_data = raw_data * slope + intercept
        
        groups_data[group_name]["channels"][channel_name] = scaled_data
        groups_data[group_name]["slope"] = slope
        
        # Determine units from group name
        if "Acceleration" in group_name:
            groups_data[group_name]["units"] = "m/s²"
        elif "Gyroscope" in group_name:
            groups_data[group_name]["units"] = "°/s"

# Default to 100 Hz if wf_increment not found
if wf_increment is None:
    wf_increment = 0.01

# Get first channel's data to determine sample count
first_group = next(iter(groups_data.values()))
first_channel_data = next(iter(first_group["channels"].values()))
num_samples = len(first_channel_data)
time_axis = [i * wf_increment for i in range(num_samples)]

# Create subplots dynamically
num_groups = len(groups_data)
fig, axes = plt.subplots(num_groups, 1, figsize=(12, 5 * num_groups))

# Handle single subplot (axes is not a list)
if num_groups == 1:
    axes = [axes]

# Plot each group
for ax, (group_name, group_info) in zip(axes, groups_data.items()):
    for channel_name, data in group_info["channels"].items():
        ax.plot(time_axis, data, label=channel_name, alpha=0.7)
    
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(group_info["units"])
    ax.set_title(f"{group_name} Data")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()
