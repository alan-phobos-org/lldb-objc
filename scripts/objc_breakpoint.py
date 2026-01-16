#!/usr/bin/env python3
"""
LLDB script for setting breakpoints on Objective-C methods, including private symbols.
Usage: obrk -[ClassName selector:with:args:]
       obrk +[ClassName classMethod:]
       obrk [ClassName selector:]  (auto-detects + or -)
       obrk --verbose -[ClassName selector:]  (enable debug output)
"""

from __future__ import annotations

import lldb
import os
import re
import sys
from typing import Any, Dict, Tuple

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

from objc_core import parse_method_signature, format_method_name

from objc_utils import resolve_method_address, detect_method_type


def _parse_args(command: str) -> Tuple[bool, str]:
    """Parse --verbose flag from command, return (verbose, remaining_command)."""
    verbose = False
    remaining = command.strip()

    # Check for --verbose or -v flag
    if remaining.startswith("--verbose ") or remaining.startswith("-v "):
        verbose = True
        remaining = remaining.split(" ", 1)[1].strip() if " " in remaining else ""
    elif remaining == "--verbose" or remaining == "-v":
        verbose = True
        remaining = ""

    return verbose, remaining


def breakpoint_on_objc_method(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Set a breakpoint on an Objective-C method by resolving it at runtime.
    Supports both public and private classes/methods.
    """
    # Parse flags
    verbose, method_spec = _parse_args(command)

    if not method_spec:
        result.SetError(
            "Usage: obrk [-v|--verbose] -[ClassName selector:]\n"
            "       obrk [-v|--verbose] +[ClassName classMethod:]\n"
            "       obrk [-v|--verbose] [ClassName selector:]  (auto-detects + or -)"
        )
        return

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if verbose:
        print(f"[DEBUG] Target: {target}")
        print(f"[DEBUG] Process: {process}")
        print(f"[DEBUG] Process state: {process.GetState() if process.IsValid() else 'invalid'}")

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    if verbose:
        print(f"[DEBUG] Thread: {thread}")
        print(f"[DEBUG] Frame: {frame}")
        print(f"[DEBUG] Frame PC: 0x{frame.GetPC():x}")

    # Parse the method signature
    is_instance_method, class_name, selector, error = parse_method_signature(method_spec)
    if error:
        result.SetError(
            f"Usage: obrk -[ClassName selector:], obrk +[ClassName selector:], or obrk [ClassName selector:]\n{error}"
        )
        return

    if verbose:
        print(f"[DEBUG] Parsed: is_instance={is_instance_method}, class={class_name}, sel={selector}")

    # Auto-detect method type if not specified
    if is_instance_method is None:
        is_instance_method = detect_method_type(frame, class_name, selector, verbose=True)

    method_name = format_method_name(class_name, selector, is_instance_method)
    print(f"Resolving {'instance' if is_instance_method else 'class'} method: {method_name}")

    # Resolve the method address
    resolved_addr, class_ptr, sel_ptr, error, raw_imp_addr = resolve_method_address(
        frame, class_name, selector, is_instance_method, verbose=True
    )

    if verbose:
        print("[DEBUG] resolve_method_address returned:")
        print(f"[DEBUG]   resolved_addr: {resolved_addr}")
        print(f"[DEBUG]   resolved_addr.IsValid(): {resolved_addr.IsValid()}")
        print(f"[DEBUG]   class_ptr: 0x{class_ptr:x}")
        print(f"[DEBUG]   sel_ptr: 0x{sel_ptr:x}")
        print(f"[DEBUG]   error: {error}")
        print(f"[DEBUG]   raw_imp_addr: 0x{raw_imp_addr:x}")

    if error:
        result.SetError(error)
        return

    # Use the raw IMP address directly from class_getMethodImplementation
    # This is the actual load address we need for breakpoints.
    # Don't use resolved_addr.GetLoadAddress() as it goes through SBAddress
    # which can have issues with iOS shared cache binaries.
    if raw_imp_addr == 0:
        result.SetError(f"Failed to resolve method address for {method_name}")
        return

    load_addr = raw_imp_addr

    if verbose:
        print(f"[DEBUG] Using raw IMP address: 0x{load_addr:x}")
        if resolved_addr.IsValid():
            # Also show the SBAddress info for comparison
            sb_load_addr = resolved_addr.GetLoadAddress(target)
            file_addr = resolved_addr.GetFileAddress()
            module = resolved_addr.GetModule()
            section = resolved_addr.GetSection()
            print(f"[DEBUG] SBAddress load addr: 0x{sb_load_addr:x} (matches: {sb_load_addr == load_addr})")
            print(f"[DEBUG] SBAddress file addr: 0x{file_addr:x}")
            print(f"[DEBUG] Module: {module.GetFileSpec() if module.IsValid() else 'invalid'}")
            print(f"[DEBUG] Section: {section.GetName() if section.IsValid() else 'invalid'}")

    # Use HandleCommand to run "breakpoint set -a <addr>" which is exactly
    # what the user would type with "b <addr>". This ensures we use the same
    # code path as the CLI command.
    cmd = f"breakpoint set -a 0x{load_addr:x} -N '{method_name}'"

    if verbose:
        print(f"[DEBUG] Running command: {cmd}")

    cmd_result = lldb.SBCommandReturnObject()
    interpreter = debugger.GetCommandInterpreter()
    interpreter.HandleCommand(cmd, cmd_result)

    if verbose:
        print(f"[DEBUG] Command succeeded: {cmd_result.Succeeded()}")
        print(f"[DEBUG] Command output: {cmd_result.GetOutput()}")
        if cmd_result.GetError():
            print(f"[DEBUG] Command error: {cmd_result.GetError()}")

    if not cmd_result.Succeeded():
        error_msg = cmd_result.GetError() or "Unknown error"
        result.SetError(f"Failed to create breakpoint at {method_name} (0x{load_addr:x}): {error_msg}")
        return

    # Extract breakpoint ID from output
    output = cmd_result.GetOutput()
    bp_match = re.search(r"Breakpoint (\d+):", output)
    if bp_match:
        bp_id = bp_match.group(1)
        print(f"\nBreakpoint #{bp_id} set at {method_name}")
    else:
        print(f"\nBreakpoint set at {method_name} (0x{load_addr:x})")
        if verbose:
            print(f"[DEBUG] Full output: {output}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.breakpoint_on_objc_method"
    debugger.HandleCommand(f'command script add -h "Set breakpoint on Objective-C method" -f {module_path} obrk')
    print(f"[lldb-objc v{__version__}] 'obrk' installed - Set breakpoints on Objective-C methods")
