#!/usr/bin/env python3
"""
LLDB script for finding instances of Objective-C classes in autorelease pools.
Usage: opool [--verbose] ClassName  # Find instances in autorelease pools
       opool NSString               # Find NSString instances
       opool NSDate                 # Find NSDate instances
       opool --verbose NSString     # Show full pool debug output

This command scans autorelease pools to find instances of the specified class.
Use --verbose to show the raw pool contents from _objc_autoreleasePoolPrint().
"""

from __future__ import annotations

import lldb
import os
import sys
import re
from typing import Any, Dict, List, Tuple

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"


def find_in_autorelease_pool(
    frame: lldb.SBFrame,
    class_name: str,
    verbose: bool = False
) -> Tuple[List[Tuple[int, str]], str]:
    """
    Find instances of a class by scanning autorelease pools.

    Args:
        frame: Current stack frame for expression evaluation
        class_name: Name of the class to search for
        verbose: If True, return the full pool contents

    Returns:
        Tuple of (instances list, pool_output string)
        instances: List of (address, description) tuples for found instances
        pool_output: Raw pool output if verbose=True, empty string otherwise
    """
    instances = []
    process = frame.GetThread().GetProcess()

    # Step 1: Get the class pointer
    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return instances, ""

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return instances, ""

    # Step 2: Scan autorelease pools
    # The _objc_autoreleasePoolPrint() function prints to stderr AND returns the string
    # We need to suppress the stderr output unless --verbose is specified

    if not verbose:
        # Redirect stderr to /dev/null to suppress debug output
        pool_expr = """
        (const char *)(({
            int saved_stderr = dup(2);
            int devnull = open("/dev/null", 1);
            dup2(devnull, 2);
            const char *result = _objc_autoreleasePoolPrint();
            dup2(saved_stderr, 2);
            close(saved_stderr);
            close(devnull);
            result;
        }))
        """
    else:
        # Let the output go to stderr naturally
        pool_expr = '(const char *)_objc_autoreleasePoolPrint()'

    pool_result = frame.EvaluateExpression(pool_expr)

    if not pool_result.IsValid() or pool_result.GetError().Fail():
        return instances, ""

    pool_addr = pool_result.GetValueAsUnsigned()
    if pool_addr == 0:
        return instances, ""

    error = lldb.SBError()
    pool_info = process.ReadCStringFromMemory(pool_addr, 1000000, error)

    if not error.Success() or not pool_info:
        return instances, ""

    pool_output = pool_info if verbose else ""

    # Parse pool info to extract addresses
    # Pool output format (from _objc_autoreleasePoolPrint):
    #   objc[PID]: [slot_addr]  object_ptr_or_marker  description
    # Examples:
    #   objc[47068]: [0x9fac10000]  ................  PAGE  (hot) (cold)
    #   objc[47068]: [0x9fac10038]  ################  POOL 0x9fac10038
    #   objc[47068]: [0x9fac10040]  0x123456789012    <NSString: "hello">
    #
    # We need to extract object addresses (not slot addresses, markers, or POOL addresses)
    collected_addresses = set()

    # Look for lines with actual object pointers (after the slot address)
    for line in pool_info.split('\n'):
        # Skip empty lines, headers, and special markers
        if not line.strip():
            continue
        if 'AUTORELEASE POOLS' in line or 'releases pending' in line or '####' in line:
            continue

        # Parse lines like: "objc[PID]: [slot_addr]  object_addr  ..."
        # or: "[slot_addr]  object_addr  ..."
        # Look for a hex address that's not a PAGE marker, POOL marker, or dots
        match = re.search(r'\[0x[0-9a-fA-F]+\]\s+(0x[0-9a-fA-F]+)', line)
        if match:
            addr_str = match.group(1)

            # Skip if this line is a PAGE or POOL marker
            if 'PAGE' in line or ('####' in line and 'POOL' in line):
                continue

            try:
                addr = int(addr_str, 16)
            except ValueError:
                continue

            if addr == 0 or addr in collected_addresses:
                continue

            # Check if this is an instance of our target class
            # Use isKindOfClass to support subclasses
            check_expr = f'(BOOL)[(id)0x{addr:x} isKindOfClass:(Class)0x{class_ptr:x}]'
            check_result = frame.EvaluateExpression(check_expr)

            if check_result.IsValid() and check_result.GetValueAsUnsigned() == 1:
                collected_addresses.add(addr)

                # Get description
                desc_expr = f'(const char *)[[(id)0x{addr:x} description] UTF8String]'
                desc_result = frame.EvaluateExpression(desc_expr)

                description = "instance"
                if desc_result.IsValid() and not desc_result.GetError().Fail():
                    desc_addr = desc_result.GetValueAsUnsigned()
                    if desc_addr != 0:
                        error2 = lldb.SBError()
                        desc_bytes = process.ReadCStringFromMemory(desc_addr, 256, error2)
                        if error2.Success() and desc_bytes:
                            description = desc_bytes

                instances.append((addr, description))

    return instances, pool_output


def find_pool_instances_command(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    LLDB command to find instances of an Objective-C class in autorelease pools.

    Usage: opool [--verbose] ClassName
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse arguments
    args = command.strip().split()

    if len(args) < 1:
        result.SetError("Usage: opool [--verbose] ClassName")
        return

    # Check for --verbose flag
    verbose = False
    if args[0] == '--verbose':
        verbose = True
        args = args[1:]

    if len(args) < 1:
        result.SetError("Usage: opool [--verbose] ClassName")
        return

    # Get current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    class_name = args[0]

    # Find instances in autorelease pools
    instances, pool_output = find_in_autorelease_pool(frame, class_name, verbose)

    # Show pool output if verbose
    if verbose and pool_output:
        print(pool_output)

    if not instances:
        print(f"No instances of {class_name} found in autorelease pools")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Display results
    for addr, description in instances:
        # Get the actual class of this instance
        class_expr = f'(const char *)class_getName((Class)object_getClass((id)0x{addr:x}))'
        class_result = frame.EvaluateExpression(class_expr)

        actual_class = class_name  # Default to searched class
        if class_result.IsValid() and not class_result.GetError().Fail():
            class_addr = class_result.GetValueAsUnsigned()
            if class_addr != 0:
                error = lldb.SBError()
                class_bytes = process.ReadCStringFromMemory(class_addr, 256, error)
                if error.Success() and class_bytes:
                    actual_class = class_bytes

        # Truncate long descriptions
        if len(description) > 100:
            description = description[:97] + "..."

        # Dim address (gray), then actual class, then description
        print(f"\033[90m0x{addr:016x}\033[0m  {actual_class}  {description}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the opool command when this module is loaded in LLDB."""
    debugger.HandleCommand(
        'command script add -f objc_pool.find_pool_instances_command opool'
    )
    print(f"[lldb-objc v{__version__}] Autorelease pool scanner 'opool' has been installed.")
