#!/usr/bin/env python3
"""
LLDB script for dumping NSData contents or raw memory to a file.

Usage:
    odump <expr> <output_path>              # Dump NSData to file
    odump <expr> <output_path> --size=N     # Dump N bytes from address
    odump <expr> <output_path> --force      # Use --force for protected memory
"""

from __future__ import annotations

import lldb
import os
import sys
from typing import Any, Dict, Optional, Tuple

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Guard against double initialization
_initialized = False


def _parse_size(size_str: str) -> Optional[int]:
    """Parse size string supporting hex (0x100) and decimal (256) formats."""
    size_str = size_str.strip()
    try:
        if size_str.startswith("0x") or size_str.startswith("0X"):
            return int(size_str, 16)
        return int(size_str)
    except ValueError:
        return None


def _parse_args(command: str) -> Tuple[Optional[str], Optional[str], Optional[int], bool, Optional[str]]:
    """
    Parse command arguments.

    Returns: (expr, output_path, size, force, error)
    """
    args = command.strip().split()
    if not args:
        return None, None, None, False, "No arguments provided"

    expr = None
    output_path = None
    size = None
    force = False

    i = 0
    positional = []

    while i < len(args):
        arg = args[i]

        if arg.startswith("--size="):
            size_str = arg[7:]
            size = _parse_size(size_str)
            if size is None:
                return None, None, None, False, f"Invalid size: {size_str}"
        elif arg == "--size":
            if i + 1 >= len(args):
                return None, None, None, False, "--size requires a value"
            i += 1
            size = _parse_size(args[i])
            if size is None:
                return None, None, None, False, f"Invalid size: {args[i]}"
        elif arg == "--force" or arg == "-f":
            force = True
        else:
            positional.append(arg)

        i += 1

    if len(positional) < 2:
        return None, None, None, False, "Requires both <expr> and <output_path>"

    # The last positional arg is the output path, everything else is the expression
    output_path = positional[-1]
    expr = " ".join(positional[:-1])

    return expr, output_path, size, force, None


def _evaluate_expression(frame: lldb.SBFrame, expr: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Evaluate expression and return address.

    Returns: (address, error)
    """
    target = frame.GetThread().GetProcess().GetTarget()

    # Try to evaluate the expression
    result = target.EvaluateExpression(expr)

    if not result.IsValid():
        return None, f"Invalid expression: {expr}"

    error = result.GetError()
    if error.Fail():
        return None, f"Expression error: {error.GetCString()}"

    # Get the address value
    addr = result.GetValueAsUnsigned(0)
    if addr == 0:
        # Check if it's actually nil or just evaluated to 0
        if "nil" in str(result.GetValue()) or addr == 0:
            return None, "Expression evaluated to nil/NULL"

    return addr, None


def _get_nsdata_info(frame: lldb.SBFrame, addr: int) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Get bytes pointer and length from NSData object.

    Returns: (bytes_addr, length, error)
    """
    target = frame.GetThread().GetProcess().GetTarget()

    # Get bytes pointer
    bytes_result = target.EvaluateExpression(f"(void *)[(NSData *)0x{addr:x} bytes]")
    if not bytes_result.IsValid() or bytes_result.GetError().Fail():
        error_msg = bytes_result.GetError().GetCString() if bytes_result.GetError().Fail() else "unknown error"
        return None, None, f"Failed to call [NSData bytes]: {error_msg}"

    bytes_addr = bytes_result.GetValueAsUnsigned(0)
    if bytes_addr == 0:
        return None, None, "NSData bytes pointer is NULL"

    # Get length
    length_result = target.EvaluateExpression(f"(unsigned long)[(NSData *)0x{addr:x} length]")
    if not length_result.IsValid() or length_result.GetError().Fail():
        error_msg = length_result.GetError().GetCString() if length_result.GetError().Fail() else "unknown error"
        return None, None, f"Failed to call [NSData length]: {error_msg}"

    length = length_result.GetValueAsUnsigned(0)
    if length == 0:
        return None, None, "NSData has zero bytes"

    return bytes_addr, length, None


def dump_memory(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Dump NSData contents or raw memory to a file.

    Usage:
        odump <expr> <output_path>              # Dump NSData to file
        odump <expr> <output_path> --size=N     # Dump N bytes from address
        odump <expr> <output_path> --force      # Use --force for protected memory

    Examples:
        odump $0 /tmp/data.bin                  # Dump NSData in $0
        odump 0x12345 /tmp/mem.bin --size=0x100 # Dump 256 bytes from address
        odump [self data] /tmp/out.bin          # Dump NSData from expression
    """
    # Parse arguments
    expr, output_path, size, force, error = _parse_args(command)

    if error:
        result.SetError(
            f"{error}\n\n"
            "Usage: odump <expr> <output_path> [--size=N] [--force]\n"
            "  <expr>        Address or ObjC expression (0x12345, $0, [self data])\n"
            "  <output_path> Output file path\n"
            "  --size=N      Raw memory mode: dump N bytes (hex 0x100 or decimal 256)\n"
            "  --force       Use --force for protected memory"
        )
        return

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Get the current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Evaluate the expression to get the address
    addr, error = _evaluate_expression(frame, expr)
    if error:
        result.SetError(error)
        return

    # Determine start address and size
    if size is not None:
        # Raw memory mode - use the address directly
        start_addr = addr
        dump_size = size
        mode = "raw memory"
    else:
        # NSData mode - get bytes and length from the object
        start_addr, dump_size, error = _get_nsdata_info(frame, addr)
        if error:
            result.SetError(error)
            return
        mode = "NSData"

    # Build the memory read command
    # Use "memory read" with --outfile to dump to file
    force_flag = " --force" if force else ""
    cmd = f"memory read --outfile '{output_path}' --binary 0x{start_addr:x} 0x{start_addr + dump_size:x}{force_flag}"

    cmd_result = lldb.SBCommandReturnObject()
    interpreter = debugger.GetCommandInterpreter()
    interpreter.HandleCommand(cmd, cmd_result)

    if not cmd_result.Succeeded():
        error_msg = cmd_result.GetError() or "Unknown error"
        result.SetError(f"Failed to dump memory: {error_msg}")
        return

    # Report success
    print(f"Dumped {dump_size} bytes ({mode}) to {output_path}")
    print(f"  Source: 0x{start_addr:x} - 0x{start_addr + dump_size:x}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.dump_memory"
    debugger.HandleCommand(f'command script add -h "Dump NSData or memory to file" -f {module_path} odump')
    print(f"[lldb-objc v{__version__}] 'odump' installed - Dump NSData or memory to file")
