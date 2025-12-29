#!/usr/bin/env python3
"""
LLDB script for setting breakpoints on Objective-C methods, including private symbols.
Usage: obrk -[ClassName selector:with:args:]
       obrk +[ClassName classMethod:]
"""

from __future__ import annotations

import lldb
import os
import sys
from typing import Any, Dict

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

from objc_utils import (
    parse_method_signature,
    resolve_method_address,
    format_method_name
)


def breakpoint_on_objc_method(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Set a breakpoint on an Objective-C method by resolving it at runtime.
    Supports both public and private classes/methods.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the method signature
    is_instance_method, class_name, selector, error = parse_method_signature(command)
    if error:
        result.SetError(f"Usage: obrk -[ClassName selector:] or obrk +[ClassName selector:]\n{error}")
        return

    method_name = format_method_name(class_name, selector, is_instance_method)
    print(f"Resolving {'instance' if is_instance_method else 'class'} method: {method_name}")

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Resolve the method address
    imp_addr, class_ptr, sel_ptr, error = resolve_method_address(
        frame, class_name, selector, is_instance_method, verbose=True
    )

    if error:
        result.SetError(error)
        return

    # Set the breakpoint
    breakpoint = target.BreakpointCreateByAddress(imp_addr)

    if not breakpoint.IsValid():
        result.SetError(f"Failed to create breakpoint at 0x{imp_addr:x}")
        return

    # Set a readable name for the breakpoint
    breakpoint.AddName(method_name)

    print(f"\nBreakpoint #{breakpoint.GetID()} set at {method_name}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Set breakpoint on Objective-C method. '
        'Usage: obrk -[ClassName selector:] or obrk +[ClassName classMethod:]" '
        '-f objc_breakpoint.breakpoint_on_objc_method obrk'
    )
    print(f"[lldb-objc v{__version__}] Objective-C breakpoint command 'obrk' has been installed.")
    print("Usage: obrk -[ClassName selector:]")
    print("       obrk +[ClassName classMethod:]")
