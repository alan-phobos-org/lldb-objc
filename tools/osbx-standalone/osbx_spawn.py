#!/usr/bin/env python3
"""
osbx_spawn.py - Spawn osbx-standalone as child of sandboxed process via LLDB

This LLDB script spawns the standalone sandbox scanner as a child process
of the currently debugged application. The child inherits the parent's
sandbox, allowing fast native scanning while in the correct sandbox context.

Usage from LLDB:
    (lldb) command script import /path/to/osbx_spawn.py
    (lldb) osbx-spawn [--json] [--output FILE] [paths...]

Or run directly:
    python3 osbx_spawn.py --lldb-attach PID [options]

This is Option C from the design: fork from sandboxed process to inherit
its sandbox context while running at native binary speed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

# Try to import lldb - may not be available when run standalone
try:
    import lldb
except ImportError:
    lldb = None

# Path to the standalone binary (relative to this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STANDALONE_BINARY = os.path.join(SCRIPT_DIR, "osbx-standalone")


def find_osbx_standalone() -> Optional[str]:
    """Find the osbx-standalone binary."""
    # Check relative to this script
    if os.path.exists(STANDALONE_BINARY):
        return STANDALONE_BINARY

    # Check in PATH
    for path_dir in os.environ.get("PATH", "").split(":"):
        candidate = os.path.join(path_dir, "osbx-standalone")
        if os.path.exists(candidate):
            return candidate

    return None


def spawn_scanner_via_lldb(
    frame,
    binary_path: str,
    output_file: str,
    json_output: bool = True,
    paths: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Spawn osbx-standalone as child of debugged process using fork/exec.

    The child process inherits the parent's sandbox restrictions.

    Args:
        frame: LLDB SBFrame of the stopped process
        binary_path: Path to osbx-standalone binary
        output_file: File to write results to
        json_output: Whether to output JSON format
        paths: Optional list of specific paths to scan

    Returns:
        Contents of output file, or None on error
    """
    if not lldb:
        print("Error: LLDB not available")
        return None

    # Build command string
    args = ["--no-sandbox"]  # Don't apply new sandbox, inherit parent's
    if json_output:
        args.append("--json")

    if paths:
        args.extend(paths)

    args_str = " ".join(args)
    cmd = f'"{binary_path}" {args_str} > "{output_file}" 2>&1'

    # Use system() to fork and exec - child inherits sandbox
    expr = f'(int)system("{cmd}")'

    print(f"Spawning scanner: {cmd}")

    result = frame.EvaluateExpression(expr)
    if not result.GetError().Success():
        print(f"Error spawning scanner: {result.GetError()}")
        return None

    exit_code = result.GetValueAsSigned()
    if exit_code != 0:
        print(f"Warning: Scanner exited with code {exit_code}")

    # Read results
    try:
        with open(output_file, "r") as f:
            return f.read()
    except IOError as e:
        print(f"Error reading results: {e}")
        return None


def osbx_spawn_command(
    debugger,
    command: str,
    result,
    internal_dict: Dict[str, Any],
) -> None:
    """
    LLDB command: Spawn standalone scanner as child of sandboxed process.

    Usage: osbx-spawn [--json] [--output FILE] [paths...]
    """
    if not lldb:
        result.SetError("LLDB not available")
        return

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Find standalone binary
    binary_path = find_osbx_standalone()
    if not binary_path:
        result.SetError(
            f"osbx-standalone not found. Build it first:\n"
            f"  cd {SCRIPT_DIR} && make"
        )
        return

    # Parse arguments
    args = command.strip().split()
    json_output = "--json" in args
    output_file = None
    paths = []

    i = 0
    while i < len(args):
        if args[i] == "--json":
            json_output = True
        elif args[i] == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 1
        elif not args[i].startswith("-"):
            paths.append(args[i])
        i += 1

    # Create temp file for results if not specified
    if not output_file:
        fd, output_file = tempfile.mkstemp(suffix=".json" if json_output else ".txt")
        os.close(fd)
        cleanup_output = True
    else:
        cleanup_output = False

    try:
        # Get current frame
        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()

        # Spawn scanner
        results = spawn_scanner_via_lldb(
            frame,
            binary_path,
            output_file,
            json_output=json_output,
            paths=paths if paths else None,
        )

        if results:
            print(results)

            # Parse and summarize if JSON
            if json_output:
                try:
                    data = json.loads(results)
                    writable = data.get("writable_paths", [])
                    print(f"\nSummary: {len(writable)} writable paths found")
                except json.JSONDecodeError:
                    pass
        else:
            result.SetError("Failed to get scanner results")

    finally:
        if cleanup_output and os.path.exists(output_file):
            os.unlink(output_file)

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Spawn standalone sandbox scanner as child process. '
        'Usage: osbx-spawn [--json] [--output FILE] [paths...]" '
        f"-f {__name__}.osbx_spawn_command osbx-spawn"
    )
    print("[osbx-spawn] Registered - Spawn standalone scanner as child of sandboxed process")


# Allow running directly for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Spawn osbx-standalone as child of sandboxed process"
    )
    parser.add_argument("--lldb-attach", type=int, help="PID to attach to")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--output", help="Output file")
    parser.add_argument("paths", nargs="*", help="Paths to scan")

    args = parser.parse_args()

    if args.lldb_attach:
        print("Direct LLDB attachment not implemented in standalone mode.")
        print("Use from within LLDB:")
        print(f"  (lldb) command script import {__file__}")
        print("  (lldb) process attach -p PID")
        print("  (lldb) osbx-spawn --json")
        sys.exit(1)
    else:
        print("Usage from LLDB:")
        print(f"  (lldb) command script import {__file__}")
        print("  (lldb) osbx-spawn [--json] [paths...]")
