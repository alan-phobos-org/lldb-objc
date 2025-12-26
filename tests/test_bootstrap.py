#!/usr/bin/env python3
"""
Bootstrap script to launch LLDB with the HelloWorld binary and set up testing environment.
This script:
1. Launches LLDB with the HelloWorld binary
2. Sets a breakpoint on main
3. Runs the process
4. Loads the IDS.framework
5. Imports the objc_breakpoint script
"""

import subprocess
import sys
import os

# Get the script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Path to HelloWorld binary
hello_world_path = os.path.join(script_dir, "HelloWorld/HelloWorld/HelloWorld")

# Path to objc_breakpoint.py
objc_breakpoint_path = os.path.join(script_dir, "objc_breakpoint.py")

# Verify paths exist
if not os.path.exists(hello_world_path):
    print(f"Error: HelloWorld binary not found at: {hello_world_path}")
    sys.exit(1)

if not os.path.exists(objc_breakpoint_path):
    print(f"Error: objc_breakpoint.py not found at: {objc_breakpoint_path}")
    sys.exit(1)

print(f"Launching LLDB with HelloWorld binary...")
print(f"Binary path: {hello_world_path}")
print(f"Script path: {objc_breakpoint_path}")
print()

# Create LLDB command sequence
lldb_commands = f"""
# Load the target binary
file {hello_world_path}

# Set breakpoint on main
b main

# Run the process
run

# Load IDS.framework (this will load the Objective-C runtime and IDS private classes)
expr (void)dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", 0x2)

# Import the objc_breakpoint script
command script import {objc_breakpoint_path}

# Display help
script print("\\n=== Ready for testing! ===\\n")
script print("Available commands:\\n")
script print("  obrk -[ClassName selector:]  - Set breakpoint on instance method")
script print("  obrk +[ClassName selector:]  - Set breakpoint on class method\\n")
script print("Example: obrk -[IDSService init]\\n")
"""

# Write commands to a temporary file
import tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.lldb', delete=False) as f:
    f.write(lldb_commands)
    command_file = f.name

try:
    # Launch LLDB with the command file
    subprocess.run(['lldb', '-s', command_file], check=False)
finally:
    # Clean up temporary file
    os.unlink(command_file)
