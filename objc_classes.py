#!/usr/bin/env python3
"""
LLDB script for finding Objective-C classes matching wildcard patterns.

Usage:
    oclasses [--reload] [--clear-cache] [--verbose] [pattern]

Examples:
    oclasses                       # List all classes (cached after first run)
    oclasses IDS*                  # All classes starting with "IDS"
    oclasses *Service              # All classes ending with "Service"
    oclasses *Navigation*          # All classes containing "Navigation"
    oclasses _UI*                  # All private UIKit classes
    oclasses --reload              # Force reload from runtime, refresh cache
    oclasses --reload IDS*         # Reload and filter
    oclasses --clear-cache         # Clear cache for current process
    oclasses --verbose IDS*        # Show detailed timing breakdown

Pattern matching:
  - With *: matches any sequence of characters
  - With ?: matches any single character
  - No wildcards: substring match (case-insensitive)

Caching:
  - Results are cached per-process for instant subsequent queries
  - First run: ~10-30 seconds for 10K classes
  - Cached run: <0.01 seconds
  - Use --reload to refresh cache when runtime state changes

Output:
  - Default: Compact single-line summary
  - --verbose: Detailed timing breakdown and resource usage
"""

import lldb
import re
import os
import sys

# Configurable batch size for class_getName() batching
# Higher values = fewer expression evaluations but larger expression parsing overhead
# Testing shows ~35 is optimal: balances expression count vs parsing time
# Use --batch-size=N flag to override, or set this default
DEFAULT_BATCH_SIZE = 35

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Global cache for class lists
# Structure: {process_id: {'classes': [class_names], 'timestamp': time, 'count': total_count}}
_class_cache = {}

def find_objc_classes(debugger, command, result, internal_dict):
    """
    Find Objective-C classes matching a wildcard pattern.
    Lists all registered classes that match the specified pattern.

    Flags:
        --reload: Force cache refresh and reload all classes from runtime
        --clear-cache: Clear the cache for the current process
        --batch-size=N or --batch-size N: Set batch size for class_getName() calls (default: 35)
        --verbose: Show detailed timing breakdown and resource usage
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the input: [--reload] [--clear-cache] [--batch-size=N] [--verbose] [pattern]
    args = command.strip().split()
    force_reload = '--reload' in args
    clear_cache = '--clear-cache' in args
    verbose = '--verbose' in args

    # Parse batch size
    batch_size = DEFAULT_BATCH_SIZE
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--batch-size='):
            # Format: --batch-size=50
            try:
                batch_size = int(arg.split('=')[1])
                if batch_size < 1:
                    batch_size = DEFAULT_BATCH_SIZE
                    print(f"Warning: Invalid batch size, using default {DEFAULT_BATCH_SIZE}")
            except ValueError:
                print(f"Warning: Invalid batch size format, using default {DEFAULT_BATCH_SIZE}")
        elif arg == '--batch-size' and i + 1 < len(args):
            # Format: --batch-size 50
            try:
                batch_size = int(args[i + 1])
                if batch_size < 1:
                    batch_size = DEFAULT_BATCH_SIZE
                    print(f"Warning: Invalid batch size, using default {DEFAULT_BATCH_SIZE}")
                # Skip the next argument since we consumed it
                i += 1
            except ValueError:
                print(f"Warning: Invalid batch size format, using default {DEFAULT_BATCH_SIZE}")
        i += 1

    # Remove flags and their values from args to get pattern
    pattern_args = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            # Skip flag
            if arg in ['--batch-size'] and i + 1 < len(args):
                # Skip the next argument too (it's the value)
                i += 1
        else:
            pattern_args.append(arg)
        i += 1

    pattern = pattern_args[0] if pattern_args else None

    # Handle cache clearing
    if clear_cache:
        pid = process.GetProcessID()
        if pid in _class_cache:
            del _class_cache[pid]
            print("Cache cleared for current process")
        else:
            print("No cache found for current process")
        if not pattern and not force_reload:
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Get all classes (with caching)
    class_names, timing, class_count, from_cache = get_all_classes(frame, pattern, force_reload, batch_size)

    # Display results
    if class_names:
        print(f"Found {len(class_names)} class(es){f' matching: {pattern}' if pattern else ''}:")
        for class_name in sorted(class_names):
            print(f"  {class_name}")
    else:
        print(f"No classes found{f' matching: {pattern}' if pattern else ''}")

    # Print timing metrics
    print()
    if verbose:
        # Detailed output
        print(f"{'─' * 70}")
        if from_cache:
            print(f"Performance Summary: (from cache)")
            print(f"  Total time:     {timing['total']:.3f}s")
            print(f"  Classes:        {class_count:,} total, {len(class_names):,} matched")
            print(f"  Source:         Cached (use --reload to refresh)")
        else:
            print(f"Performance Summary:")
            print(f"  Total time:     {timing['total']:.2f}s")
            print(f"  Classes:        {class_count:,} total, {len(class_names):,} matched")
            print(f"  Throughput:     {class_count / timing['total']:.0f} classes/sec")
            print(f"  Batch size:     {batch_size}")
            print(f"\n  Timing breakdown:")
            print(f"    Setup:        {timing['setup']:.2f}s ({timing['setup'] / timing['total'] * 100:.1f}%)")
            print(f"    Bulk read:    {timing['bulk_read']:.2f}s ({timing['bulk_read'] / timing['total'] * 100:.1f}%)")
            print(f"    Batching:     {timing['batching']:.2f}s ({timing['batching'] / timing['total'] * 100:.1f}%)")
            print(f"    Cleanup:      {timing['cleanup']:.2f}s ({timing['cleanup'] / timing['total'] * 100:.1f}%)")
            print(f"\n  Resource usage:")
            print(f"    Expressions:  {timing['expression_count']:,}")
            print(f"    Memory reads: {timing['memory_read_count']:,}")
        print(f"{'─' * 70}")
    else:
        # Compact output
        if from_cache:
            print(f"[{class_count:,} total | {len(class_names):,} matched | {timing['total']:.3f}s | cached]")
        else:
            print(f"[{class_count:,} total | {len(class_names):,} matched | {timing['total']:.2f}s | {class_count / timing['total']:.0f} classes/sec]")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def matches_pattern(class_name, pattern):
    """
    Check if class name matches the pattern.
    Supports wildcards: * (any characters) and ? (single character)
    Also supports simple substring matching if no wildcards present.
    """
    if pattern is None:
        return True

    # Check if pattern contains wildcard characters
    has_wildcards = '*' in pattern or '?' in pattern

    if has_wildcards:
        # Convert wildcard pattern to regex
        # Escape special regex characters except * and ?
        regex_pattern = re.escape(pattern)
        # Replace escaped wildcards with regex equivalents
        regex_pattern = regex_pattern.replace(r'\*', '.*')
        regex_pattern = regex_pattern.replace(r'\?', '.')
        # Make it match the whole string and case-insensitive
        regex_pattern = f'^{regex_pattern}$'
        try:
            return bool(re.match(regex_pattern, class_name, re.IGNORECASE))
        except re.error:
            # Fallback to substring match if regex is invalid
            return pattern.lower() in class_name.lower()
    else:
        # Simple substring matching (case-insensitive)
        return pattern.lower() in class_name.lower()

def build_batch_expression(class_pointers_batch):
    """
    Build a compound expression that calls class_getName() for multiple classes
    and consolidates the results into a single buffer.

    Args:
        class_pointers_batch: List of class pointer addresses (e.g., 100 classes)

    Returns:
        String containing the compound expression

    The returned buffer format is:
        [offset_array][string_data]
        - offset_array: (batch_size + 1) integers (offsets into string_data + total size)
        - string_data: concatenated null-terminated strings

    Note: Uses a helper function approach since LLDB doesn't support GCC statement expressions.
    We define and immediately call a lambda-like block.
    """
    batch_size = len(class_pointers_batch)

    # Allocate buffer: offsets ((batch_size + 1) * 4 bytes) + string space (estimated)
    # Estimate ~40 bytes per class name on average
    offset_size = (batch_size + 1) * 4
    string_estimate = 40 * batch_size
    buffer_size = offset_size + string_estimate

    # Build expression using Objective-C block (LLDB doesn't support GCC statement expressions)
    expr = f'''
(void *)(^{{
    char *buffer = (char *)malloc({buffer_size});
    if (!buffer) return (void *)0;
    unsigned int *offsets = (unsigned int *)buffer;
    char *string_data = buffer + {offset_size};
    unsigned int current_offset = 0;
'''

    for i, class_ptr in enumerate(class_pointers_batch):
        if class_ptr != 0:
            expr += f'''
    const char *name_{i} = (const char *)class_getName((Class)0x{class_ptr:x});
    if (name_{i}) {{
        offsets[{i}] = current_offset;
        size_t len = (size_t)strlen(name_{i}) + 1;
        if (current_offset + len < {string_estimate}) {{
            (void)memcpy(string_data + current_offset, name_{i}, len);
            current_offset += len;
        }}
    }} else {{
        offsets[{i}] = 0xFFFFFFFF;
    }}
'''
        else:
            expr += f'    offsets[{i}] = 0xFFFFFFFF;\n'

    expr += f'''
    offsets[{batch_size}] = current_offset;
    return (void *)buffer;
}}())
'''

    return expr


def read_consolidated_string_buffer(batch_result, batch_size, process, frame, pattern=None):
    """
    Read class names from a consolidated string buffer.

    Args:
        batch_result: SBValue pointing to consolidated buffer
        batch_size: Number of classes in the batch
        process: SBProcess object
        frame: SBFrame object for cleanup
        pattern: Optional pattern to filter by

    Returns:
        List of class names matching the pattern
    """
    import struct

    buffer_ptr = batch_result.GetValueAsUnsigned()

    if buffer_ptr == 0:
        return []

    error = lldb.SBError()

    # Read offset array (batch_size + 1 integers)
    offset_array_size = (batch_size + 1) * 4
    offset_bytes = process.ReadMemory(buffer_ptr, offset_array_size, error)

    if not error.Success():
        frame.EvaluateExpression(f'(void)free((void *)0x{buffer_ptr:x})')
        return []

    # Parse offsets
    offsets = struct.unpack(f'{batch_size + 1}I', offset_bytes)
    total_string_size = offsets[-1]  # Last offset is total size

    # Read entire string data buffer in one shot
    string_data_ptr = buffer_ptr + offset_array_size
    string_data = process.ReadMemory(string_data_ptr, total_string_size, error)

    # Free the buffer
    frame.EvaluateExpression(f'(void)free((void *)0x{buffer_ptr:x})')

    if not error.Success():
        return []

    # Extract individual strings from consolidated buffer
    class_names = []

    for i in range(batch_size):
        offset = offsets[i]
        if offset == 0xFFFFFFFF:
            continue

        # Find null terminator
        next_offset = offsets[i + 1] if i + 1 < batch_size else total_string_size
        if i + 1 < batch_size and offsets[i + 1] != 0xFFFFFFFF:
            next_offset = offsets[i + 1]
        else:
            # Find the null terminator manually
            null_pos = string_data.find(b'\0', offset)
            if null_pos == -1:
                continue
            next_offset = null_pos + 1

        # Extract string
        try:
            class_name = string_data[offset:next_offset - 1].decode('utf-8')

            # Apply pattern filter
            if pattern is None or matches_pattern(class_name, pattern):
                class_names.append(class_name)
        except (UnicodeDecodeError, IndexError):
            continue

    return class_names


def get_all_classes(frame, pattern=None, force_reload=False, batch_size=None):
    """
    Get all Objective-C classes using objc_copyClassList.
    Returns a list of class names matching the pattern.

    Optimized implementation using consolidated string buffers:
    - Batches class_getName() calls into configurable groups
    - Consolidates string data into single buffers
    - Reduces expression evaluations from ~10K to ~100
    - Reduces memory reads from ~10K to ~200
    - Caches results per-process for instant subsequent queries

    For 10,000 classes:
    - First run: ~10-30 seconds
    - Cached run: <0.01 seconds

    Args:
        frame: LLDB frame for expression evaluation
        pattern: Optional pattern to filter class names
        force_reload: If True, bypass cache and reload from runtime
        batch_size: Number of classes to process per batch (default: DEFAULT_BATCH_SIZE)

    Returns:
        Tuple of (class_names, timing_dict, class_count, from_cache)
    """
    if batch_size is None:
        batch_size = DEFAULT_BATCH_SIZE
    import struct
    import time

    process = frame.GetThread().GetProcess()
    pid = process.GetProcessID()

    start_time = time.time()

    # Check cache first
    if not force_reload and pid in _class_cache:
        cache_entry = _class_cache[pid]
        all_classes = cache_entry['classes']
        class_count = cache_entry['count']

        # Filter by pattern
        if pattern:
            filtered_classes = [c for c in all_classes if matches_pattern(c, pattern)]
        else:
            filtered_classes = all_classes

        # Create minimal timing info for cached results
        timing = {
            'total': time.time() - start_time,
            'setup': 0,
            'bulk_read': 0,
            'batching': 0,
            'cleanup': 0,
            'expression_count': 0,
            'memory_read_count': 0
        }

        return filtered_classes, timing, class_count, True

    # Not in cache or forced reload - enumerate from runtime
    # Detailed timing metrics
    timing = {
        'total': 0,
        'setup': 0,
        'bulk_read': 0,
        'batching': 0,
        'cleanup': 0,
        'expression_count': 0,
        'memory_read_count': 0
    }
    setup_start = time.time()

    # Steps 1-3: Same as Phase 1/2 (get class pointer array via bulk read)
    # Allocate count variable
    count_var_expr = f'(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)
    timing['expression_count'] += 1

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        print(f"Warning: Failed to allocate count variable")
        return []

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Get class list using objc_copyClassList
    class_list_expr = f'(void *)objc_copyClassList((unsigned int *)0x{count_var_ptr:x})'
    class_list_result = frame.EvaluateExpression(class_list_expr)
    timing['expression_count'] += 1

    if not class_list_result.IsValid() or class_list_result.GetError().Fail():
        print(f"Warning: objc_copyClassList failed: {class_list_result.GetError()}")
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return []

    class_list_ptr = class_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)
    timing['expression_count'] += 1

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        print(f"Warning: Failed to read class count")
        if class_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return []

    class_count = count_read_result.GetValueAsUnsigned()

    timing['setup'] = time.time() - setup_start
    bulk_read_start = time.time()

    # Bulk read the class pointer array (same as Phase 1/2)
    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()
    array_size = class_count * pointer_size

    error = lldb.SBError()
    class_array_bytes = process.ReadMemory(class_list_ptr, array_size, error)
    timing['memory_read_count'] += 1

    if not error.Success():
        print(f"Error: Failed to read class array from memory: {error}")
        if class_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return []

    # Parse class pointers in Python (fast - no LLDB overhead)
    if pointer_size == 8:
        format_str = f'{class_count}Q'  # 64-bit unsigned pointers
    else:
        format_str = f'{class_count}I'  # 32-bit unsigned pointers

    class_pointers = struct.unpack(format_str, class_array_bytes)

    timing['bulk_read'] = time.time() - bulk_read_start
    batching_start = time.time()

    # PHASE 3 OPTIMIZATION: Use consolidated string buffers
    class_names = []

    num_batches = (len(class_pointers) + batch_size - 1) // batch_size

    if len(class_pointers) > 1000:
        print(f"Processing {len(class_pointers)} classes in {num_batches} batches (batch_size={batch_size})...")

    for batch_idx in range(0, len(class_pointers), batch_size):
        batch_end = min(batch_idx + batch_size, len(class_pointers))
        batch = class_pointers[batch_idx:batch_end]
        current_batch_size = len(batch)

        # Build compound expression with consolidated string buffer
        batch_expr = build_batch_expression(batch)

        # Execute batch expression
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if not batch_result.IsValid() or batch_result.GetError().Fail():
            # Fallback: process each class individually if batch expression fails
            for class_ptr in batch:
                if class_ptr == 0:
                    continue
                class_name_expr = f'(const char *)class_getName((void *)0x{class_ptr:x})'
                class_name_result = frame.EvaluateExpression(class_name_expr)
                timing['expression_count'] += 1
                if class_name_result.IsValid():
                    class_name = class_name_result.GetSummary()
                    if class_name:
                        class_name = class_name.strip('"')
                        # Add all classes to cache (no pattern filtering here)
                        class_names.append(class_name)
            continue

        # Read consolidated string buffer (without pattern filtering - get all classes)
        batch_names = read_consolidated_string_buffer(
            batch_result, current_batch_size, process, frame, pattern=None
        )
        timing['expression_count'] += 1  # For free() in read_consolidated_string_buffer
        timing['memory_read_count'] += 2  # One for offsets, one for string data

        class_names.extend(batch_names)

        # Progress indicator for large operations
        if len(class_pointers) > 1000 and (batch_idx // batch_size) % 10 == 0 and batch_idx > 0:
            progress = (batch_idx / len(class_pointers)) * 100
            print(f"  Progress: {progress:.0f}%", end='\r')

    if len(class_pointers) > 1000:
        print()  # Clear progress line

    timing['batching'] = time.time() - batching_start
    cleanup_start = time.time()

    # Clean up allocated memory
    if class_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
        timing['expression_count'] += 1
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
    timing['expression_count'] += 1

    timing['cleanup'] = time.time() - cleanup_start
    timing['total'] = time.time() - start_time

    # Store in cache (unfiltered list)
    _class_cache[pid] = {
        'classes': class_names,
        'count': class_count,
        'timestamp': time.time()
    }

    # Filter by pattern if needed
    if pattern:
        filtered_classes = [c for c in class_names if matches_pattern(c, pattern)]
    else:
        filtered_classes = class_names

    return filtered_classes, timing, class_count, False


def __lldb_init_module(debugger, internal_dict):
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -f objc_classes.find_objc_classes oclasses'
    )
    print(f"[lldb-objc v{__version__}] Objective-C class finder command 'oclasses' has been installed.")
    print("Usage: oclasses [pattern]")
