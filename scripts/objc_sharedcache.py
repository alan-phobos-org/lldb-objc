#!/usr/bin/env python3
"""
LLDB script for displaying dyld shared cache information.

Usage:
    osc              # Show shared cache info
    osc --verbose    # Show detailed debug info
"""

from __future__ import annotations

import lldb
from typing import Any, Dict, Optional, Tuple

from objc_utils import register_command, require_stopped_process, evaluate_expression
from objc_core import ANSI_DIM, ANSI_RESET, ANSI_BOLD

_initialized = False


def get_shared_cache_info(frame: lldb.SBFrame, verbose: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Get shared cache information from the current process.

    Returns: (cache_info_dict, error)
    """
    cache_info = {}

    # Get shared cache range (base address and size)
    if verbose:
        print("[DEBUG] Getting shared cache range...")

    expr_range = """
({
    struct { uint64_t base; uint64_t size; } result;
    size_t len = 0;
    result.base = (uint64_t)_dyld_get_shared_cache_range(&len);
    result.size = (uint64_t)len;
    result;
})
"""

    result = evaluate_expression(frame, expr_range)

    if not result.IsValid() or result.GetError().Fail():
        return None, f"Failed to get shared cache range: {result.GetError().GetCString()}"

    base_child = result.GetChildMemberWithName("base")
    size_child = result.GetChildMemberWithName("size")

    if not base_child.IsValid() or not size_child.IsValid():
        return None, "Failed to read shared cache range values"

    base = base_child.GetValueAsUnsigned(0)
    size = size_child.GetValueAsUnsigned(0)

    if base == 0 or size == 0:
        return None, "No shared cache in use by this process"

    cache_info["base"] = base
    cache_info["size"] = size
    cache_info["end"] = base + size

    if verbose:
        print(f"[DEBUG] Base: 0x{base:x}, Size: {size}")

    # Get shared cache UUID
    # Read directly from cache header at offset 0x58 (88 bytes) as two uint64_t values
    if verbose:
        print("[DEBUG] Getting shared cache UUID from cache header...")

    # Read UUID as two 64-bit values (little-endian)
    expr_uuid_high = f"*(uint64_t *)((char *)0x{base:x} + 0x58)"
    expr_uuid_low = f"*(uint64_t *)((char *)0x{base:x} + 0x60)"

    result_high = evaluate_expression(frame, expr_uuid_high)
    result_low = evaluate_expression(frame, expr_uuid_low)

    if result_high.IsValid() and result_low.IsValid() and \
       not result_high.GetError().Fail() and not result_low.GetError().Fail():
        uuid_high = result_high.GetValueAsUnsigned(0)
        uuid_low = result_low.GetValueAsUnsigned(0)

        if uuid_high != 0 or uuid_low != 0:
            # Extract bytes from the two uint64_t values (little-endian)
            uuid_bytes = []
            for i in range(8):
                uuid_bytes.append((uuid_high >> (i * 8)) & 0xFF)
            for i in range(8):
                uuid_bytes.append((uuid_low >> (i * 8)) & 0xFF)

            # Format as standard UUID string
            uuid_str = "{:02x}{:02x}{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}".format(
                *uuid_bytes
            )
            cache_info["uuid"] = uuid_str.upper()

            if verbose:
                print(f"[DEBUG] UUID: {uuid_str}")

    # Get shared cache file path
    if verbose:
        print("[DEBUG] Getting shared cache file path...")

    expr_path = "(const char *)dyld_shared_cache_file_path()"

    result_path = evaluate_expression(frame, expr_path)

    if result_path.IsValid() and not result_path.GetError().Fail():
        path_addr = result_path.GetValueAsUnsigned(0)
        if path_addr != 0:
            process = frame.GetThread().GetProcess()
            error = lldb.SBError()
            # Read up to 512 bytes for the path
            path_data = process.ReadCStringFromMemory(path_addr, 512, error)
            if not error.Fail() and path_data:
                cache_info["path"] = path_data

                if verbose:
                    print(f"[DEBUG] Path: {path_data}")

    return cache_info, None


def get_shared_region_start(frame: lldb.SBFrame, base_addr: int, verbose: bool = False) -> Optional[int]:
    """
    Read the sharedRegionStart field from the cache header in process memory.

    The dyld cache header contains the preferred base address (sharedRegionStart)
    that the cache was built to load at. This allows calculating ASLR slide.

    Args:
        frame: LLDB frame to evaluate expressions in
        base_addr: Base address where cache is currently loaded
        verbose: Print debug info

    Returns:
        The sharedRegionStart value, or None if unable to read
    """
    if verbose:
        print(f"[DEBUG] Reading sharedRegionStart from cache header at 0x{base_addr:x}")

    # dyld_cache_header structure
    # sharedRegionStart is at offset 0xE0 (224 bytes) in modern dyld cache format
    expr = f"""
({{
    // Read sharedRegionStart directly from memory at known offset
    uint64_t *ptr = (uint64_t *)((char *)0x{base_addr:x} + 0xE0);
    *ptr;
}})
"""

    result = evaluate_expression(frame, expr)

    if not result.IsValid() or result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to read sharedRegionStart: {result.GetError().GetCString()}")
        return None

    shared_region_start = result.GetValueAsUnsigned(0)

    if verbose:
        print(f"[DEBUG] sharedRegionStart: 0x{shared_region_start:x}")

    # Sanity check: sharedRegionStart should be a reasonable address
    # arm64/arm64e: ~0x180000000 (6GB), x86_64: ~0x7FFF20000000
    # Valid range: 0x100000000 (4GB) to 0x800000000000 (128TB)
    if shared_region_start < 0x100000000 or shared_region_start > 0x800000000000:
        if verbose:
            print(f"[DEBUG] Invalid sharedRegionStart value: 0x{shared_region_start:x}")
        return None

    return shared_region_start


def show_shared_cache_info(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Show dyld shared cache information.

    Usage:
        osc              # Show shared cache info
        osc --verbose    # Show detailed debug info
    """
    # Parse flags
    verbose = "--verbose" in command or "-v" in command

    stopped = require_stopped_process(debugger, result)
    if not stopped:
        return
    frame, process = stopped

    # Get shared cache info
    cache_info, error = get_shared_cache_info(frame, verbose)

    if error:
        result.SetError(f"Failed to get shared cache info: {error}")
        return

    if cache_info is None:
        result.SetError("No shared cache information available")
        return

    # Display the shared cache information
    print("Dyld Shared Cache")
    print()

    # Size (formatted nicely)
    if "size" in cache_info:
        size_bytes = cache_info["size"]
        if size_bytes >= 1024 * 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        elif size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.2f} KB"
        else:
            size_str = f"{size_bytes} bytes"
        print(f"  Size:             {size_str} {ANSI_DIM}({size_bytes:,} bytes){ANSI_RESET}")

    # Address range
    if "base" in cache_info and "end" in cache_info:
        base = cache_info['base']
        end = cache_info['end']
        print(f"  Range:            {ANSI_DIM}0x{base:016x} - 0x{end:016x}{ANSI_RESET}")

    # Calculate and display slide
    if "base" in cache_info:
        base = cache_info['base']
        shared_region_start = get_shared_region_start(frame, base, verbose)

        if shared_region_start:
            slide = base - shared_region_start
            print(f"  Preferred base:   {ANSI_DIM}0x{shared_region_start:016x}{ANSI_RESET}")
            print(f"  ASLR slide:       {ANSI_BOLD}0x{slide:016x}{ANSI_RESET}")
        else:
            print(f"  Loaded at:        {ANSI_DIM}0x{base:016x}{ANSI_RESET} (slide unknown)")

    # UUID
    if "uuid" in cache_info:
        print()
        print(f"  UUID:             {cache_info['uuid']}")

    # File path
    if "path" in cache_info:
        print(f"  Path:             {ANSI_DIM}{cache_info['path']}{ANSI_RESET}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    register_command(
        debugger,
        "osc",
        "show_shared_cache_info",
        __name__,
        "Show dyld shared cache information",
        "Display dyld shared cache information (base, size, UUID, path)",
    )
