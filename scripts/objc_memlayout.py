#!/usr/bin/env python3
"""
LLDB script for displaying process memory layout.

Usage: omemlayout    # Show memory layout (stacks, heap, shared regions)

This command displays the memory layout of the running process, including:
- Stack regions for each thread
- Heap regions (malloc zones)
- Shared region (dyld shared cache)
"""

from __future__ import annotations

import lldb
from typing import Any, Dict, List, Optional

from objc_core import ANSI_DIM, ANSI_RESET
from objc_utils import evaluate_expression, register_command, require_stopped_process

_initialized = False


def format_size(bytes_val: int) -> str:
    """Convert byte count to human-readable format.

    Args:
        bytes_val: Size in bytes

    Returns:
        Human-readable string like "4 KB", "1 MB", "512 MB"
    """
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val // 1024} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val // (1024 * 1024)} MB"
    else:
        return f"{bytes_val // (1024 * 1024 * 1024)} GB"


def format_permissions(read: bool, write: bool, execute: bool) -> str:
    """Format permission flags as rwx string.

    Args:
        read: Read permission
        write: Write permission
        execute: Execute permission

    Returns:
        String like "rw-", "r-x", "rwx", "---"
    """
    r = "r" if read else "-"
    w = "w" if write else "-"
    x = "x" if execute else "-"
    return f"{r}{w}{x}"


def get_stack_regions(process: lldb.SBProcess) -> List[Dict[str, Any]]:
    """Enumerate stack regions for all threads.

    Args:
        process: The LLDB process

    Returns:
        List of dicts with thread_id, base, end, size
    """
    stacks = []

    for thread in process:
        if not thread.IsValid():
            continue

        # Get stack pointer from first frame
        if thread.GetNumFrames() == 0:
            continue

        frame = thread.GetFrameAtIndex(0)
        if not frame.IsValid():
            continue

        sp = frame.GetSP()
        if sp == 0:
            continue

        # Scan all frames to find min/max SP (stack bounds)
        min_sp = sp
        max_sp = sp

        for i in range(thread.GetNumFrames()):
            frame = thread.GetFrameAtIndex(i)
            if frame.IsValid():
                frame_sp = frame.GetSP()
                if frame_sp != 0:
                    min_sp = min(min_sp, frame_sp)
                    max_sp = max(max_sp, frame_sp)

        # Add some buffer for red zone and frame data
        # Stack typically grows down, so min_sp is the bottom
        stack_red_zone = 128
        stack_size = max_sp - min_sp + stack_red_zone

        stacks.append(
            {
                "thread_id": thread.GetThreadID(),
                "base": min_sp,
                "end": max_sp + stack_red_zone,
                "size": stack_size,
            }
        )

    return stacks


def get_heap_regions(process: lldb.SBProcess, frame: lldb.SBFrame) -> List[Dict[str, Any]]:
    """Enumerate heap regions using malloc zones.

    Args:
        process: The LLDB process
        frame: Stack frame for expression evaluation

    Returns:
        List of dicts with zone_id, base, end, size
    """
    # Try a simpler expression to get basic heap info
    # Use malloc default zone as a starting point
    zone_expr = "(void*)malloc_default_zone()"
    zone_result = evaluate_expression(frame, zone_expr)

    heap_regions = []

    if zone_result.IsValid() and not zone_result.GetError().Fail():
        default_zone = zone_result.GetValueAsUnsigned(0)
        if default_zone != 0:
            heap_regions.append({"zone_id": 0, "base": default_zone, "end": default_zone, "size": 0, "name": "default"})

    # Try to get additional zones using malloc_get_all_zones
    zones_expr = """
(unsigned int)({
    vm_address_t *zones = 0;
    unsigned int num = 0;
    kern_return_t err = (kern_return_t)malloc_get_all_zones(0, 0, &zones, &num);
    (err == 0) ? num : 0;
})
"""

    count_result = evaluate_expression(frame, zones_expr)
    if count_result.IsValid() and not count_result.GetError().Fail():
        num_zones = count_result.GetValueAsUnsigned(0)
        if num_zones > len(heap_regions):
            # We know there are more zones, report them as detected
            for i in range(len(heap_regions), min(num_zones, 10)):
                heap_regions.append(
                    {
                        "zone_id": i,
                        "base": 0,  # Address unknown
                        "end": 0,
                        "size": 0,
                        "name": f"zone {i}",
                    }
                )

    return heap_regions


def get_shared_region(process: lldb.SBProcess, frame: lldb.SBFrame) -> Optional[Dict[str, Any]]:
    """Find the dyld shared cache region.

    Args:
        process: The LLDB process
        frame: Stack frame for expression evaluation

    Returns:
        Dict with base, end, size, or None if not found
    """
    # Simpler approach: Look for the dyld_shared_cache using _dyld_get_shared_cache_range
    # This is a public API that returns the shared cache location
    expr = """
(struct { uint64_t base; uint64_t size; }) ({
    struct { uint64_t base; uint64_t size; } result;
    size_t len = 0;
    result.base = (uint64_t)_dyld_get_shared_cache_range(&len);
    result.size = (uint64_t)len;
    result;
})
"""

    result = evaluate_expression(frame, expr)

    if not result.IsValid() or result.GetError().Fail():
        return None

    base_child = result.GetChildMemberWithName("base")
    size_child = result.GetChildMemberWithName("size")

    if not base_child.IsValid() or not size_child.IsValid():
        return None

    base = base_child.GetValueAsUnsigned(0)
    size = size_child.GetValueAsUnsigned(0)

    if base == 0 or size == 0:
        return None

    return {
        "base": base,
        "end": base + size,
        "size": size,
    }


def show_memory_layout(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """Display memory layout of the process.

    Args:
        debugger: LLDB debugger instance
        command: Command arguments (currently unused)
        result: Command result object
        internal_dict: Internal LLDB dict
    """
    # Validate process is stopped
    stopped = require_stopped_process(debugger, result)
    if not stopped:
        return

    frame, process = stopped
    target = process.GetTarget()

    # Get process info
    pid = process.GetProcessID()
    process_name = target.GetExecutable().GetFilename()

    print(f"Memory Layout for process {pid} ({process_name})\n")

    # Get stack regions
    stacks = get_stack_regions(process)

    print(f"STACKS ({len(stacks)} thread{'s' if len(stacks) != 1 else ''}):")
    if stacks:
        for stack in stacks:
            thread_id = stack["thread_id"]
            base = stack["base"]
            end = stack["end"]
            size = stack["size"]
            size_str = format_size(size)
            perms = format_permissions(True, True, False)  # rw-
            addr_range = f"0x{base:016x}-0x{end:016x}"
            print(f"  {ANSI_DIM}Thread #{thread_id:2d}  {addr_range}{ANSI_RESET}  {size_str:>7}  [{perms}]")
    else:
        print(f"  {ANSI_DIM}No threads found{ANSI_RESET}")

    print()

    # Get heap regions
    heap_regions = get_heap_regions(process, frame)

    print(f"HEAP REGIONS ({len(heap_regions)} zone{'s' if len(heap_regions) != 1 else ''}):")
    if heap_regions:
        for region in heap_regions:
            zone_id = region["zone_id"]
            base = region["base"]
            name = region.get("name", f"zone {zone_id}")
            # For zones, we don't have exact size, so just show the zone address
            if base != 0:
                print(f"  {ANSI_DIM}Zone {zone_id}     0x{base:016x}{ANSI_RESET}  ({name})  [rw-]")
            else:
                print(f"  {ANSI_DIM}Zone {zone_id}     (detected){ANSI_RESET}  ({name})  [rw-]")
    else:
        print(f"  {ANSI_DIM}Not detected{ANSI_RESET}")

    print()

    # Get shared region
    shared_region = get_shared_region(process, frame)

    print("SHARED REGION (dyld shared cache):")
    if shared_region:
        base = shared_region["base"]
        end = shared_region["end"]
        size = shared_region["size"]
        size_str = format_size(size)
        perms = format_permissions(True, False, True)  # r-x
        print(f"  {ANSI_DIM}Region     0x{base:016x}-0x{end:016x}{ANSI_RESET}  {size_str:>7}  [{perms}]")
    else:
        print(f"  {ANSI_DIM}Not detected{ANSI_RESET}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module when loaded by LLDB.

    Args:
        debugger: LLDB debugger instance
        internal_dict: Internal LLDB dict
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    register_command(
        debugger,
        "omemlayout",
        "show_memory_layout",
        __name__,
        "Show memory layout (stacks, heap, shared region)",
        "Display region information for stacks, heap, and shared cache",
    )
