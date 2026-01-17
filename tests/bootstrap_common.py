"""Common utilities for LLDB bootstrap scripts."""

import os
import subprocess
import sys
import tempfile

# Get paths relative to this file
_this_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_this_dir)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

# Binary paths
HELLOWORLD_PATH = os.path.join(PROJECT_ROOT, "examples/HelloWorld/HelloWorld/HelloWorld")
HELLOWORLD_OPTIMISED_PATH = os.path.join(PROJECT_ROOT, "examples/HelloWorld-Optimised/HelloWorld/HelloWorld")
HELLOWORLD_SANDBOXED_PATH = os.path.join(PROJECT_ROOT, "examples/HelloWorld-Sandboxed/HelloWorld/HelloWorld")


def verify_paths(binary_path: str, build_hint: str = None) -> None:
    """Verify required paths exist, exit with error if not."""
    if not os.path.exists(binary_path):
        print(f"Error: Binary not found at: {binary_path}")
        if build_hint:
            print(f"Build it first: {build_hint}")
        sys.exit(1)

    if not os.path.exists(SCRIPTS_DIR):
        print(f"Error: scripts directory not found at: {SCRIPTS_DIR}")
        sys.exit(1)


def run_lldb_session(binary_path: str, commands: str) -> None:
    """Run an interactive LLDB session with the given commands."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".lldb", delete=False) as f:
        f.write(commands)
        command_file = f.name

    try:
        subprocess.run(["lldb", "-s", command_file], check=False)
    finally:
        os.unlink(command_file)


def make_commands_with_main_breakpoint(binary_path: str) -> str:
    """Generate LLDB commands that break on main symbol."""
    return f"""
# Load the target binary
file {binary_path}

# Load LLDB Objective-C commands
command script import {SCRIPTS_DIR}

# Set breakpoint on main
b main

# Run the process
run

# Delete the main breakpoint now that we've hit it
breakpoint delete 1

# Load CoreSymbolication.framework for additional testing
expr (void)dlopen("/System/Library/PrivateFrameworks/CoreSymbolication.framework/CoreSymbolication", 0x2)
"""


def make_commands_with_stop_at_entry(binary_path: str) -> str:
    """Generate LLDB commands that keep the process stopped for safe expression eval.

    Uses objc_autoreleasePoolPush breakpoint instead of --stop-at-entry because
    --stop-at-entry stops before dyld finishes loading, making dlopen unavailable.
    objc_autoreleasePoolPush is called in main() after the runtime is fully initialized.
    """
    return f"""
# Load the target binary
file {binary_path}

# Load LLDB Objective-C commands
command script import {SCRIPTS_DIR}

# Break on autoreleasePoolPush - called in main() when ObjC runtime is ready
# (--stop-at-entry stops before dyld loads, making dlopen unavailable)
breakpoint set -n objc_autoreleasePoolPush --one-shot true
run

# Load CoreSymbolication.framework for additional testing while stopped
expr (void)dlopen("/System/Library/PrivateFrameworks/CoreSymbolication.framework/CoreSymbolication", 0x2)
"""


def make_commands_for_sandboxed_binary(binary_path: str) -> str:
    """Generate LLDB commands for sandboxed binary testing.

    Uses sandbox_init as the breakpoint since the binary is non-optimised
    and symbols are readily available. This stops just before sandbox is applied.
    """
    return f"""
# Load the target binary
file {binary_path}

# Load LLDB Objective-C commands
command script import {SCRIPTS_DIR}

# Break on sandbox_init - stops right before sandbox restrictions are applied
# (binary is non-optimised so symbols are easy to find)
breakpoint set -n sandbox_init --one-shot true
run

# Load CoreSymbolication.framework for additional testing while stopped
expr (void)dlopen("/System/Library/PrivateFrameworks/CoreSymbolication.framework/CoreSymbolication", 0x2)
"""
