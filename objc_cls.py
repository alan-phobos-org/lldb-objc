#!/usr/bin/env python3
"""
LLDB script for finding Objective-C classes matching wildcard patterns.

Usage:
    ocls [--reload] [--clear-cache] [--verbose] [--ivars] [--properties] [pattern]

Examples:
    ocls                       # List all classes (cached after first run)
    ocls IDSService            # Exact match for "IDSService" class (fast-path)
    ocls IDS*                  # All classes starting with "IDS" (wildcard)
    ocls *Service              # All classes ending with "Service" (wildcard)
    ocls *Navigation*          # All classes containing "Navigation" (wildcard)
    ocls _UI*                  # All private UIKit classes (wildcard)
    ocls --reload              # Force reload from runtime, refresh cache
    ocls --reload IDS*         # Reload and filter
    ocls --clear-cache         # Clear cache for current process
    ocls --verbose IDS*        # Show detailed timing breakdown
    ocls --ivars NSObject      # Show instance variables for NSObject
    ocls --properties UIView   # Show properties for UIView
    ocls --ivars --properties UIViewController  # Show both ivars and properties

Pattern matching:
  - No wildcards: exact match (case-sensitive) - uses fast-path lookup
  - With *: matches any sequence of characters (case-insensitive)
  - With ?: matches any single character (case-insensitive)

Performance:
  - Fast-path (exact match): <0.01 seconds (bypasses full enumeration)
  - First run with wildcards/listing all: ~10-30 seconds for 10K classes
  - Cached run: <0.01 seconds
  - Use --reload to refresh cache when runtime state changes

Output modes (based on number of matches):
  - 1 match: Detailed view showing full class hierarchy
    - --ivars: Show instance variables (name and type encoding)
    - --properties: Show properties (name and attributes)
  - 2-20 matches: Compact one-liner showing hierarchy for each class
  - 21+ matches: Simple class name list
  - --verbose: Adds detailed timing breakdown and resource usage
"""

from __future__ import annotations

import lldb
import os
import re
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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

from objc_utils import unquote_string

# Type aliases
TimingDict = Dict[str, Any]
CacheEntry = Dict[str, Any]

# Global cache for class lists
# Structure: {process_id: {'classes': [class_names], 'timestamp': time, 'count': total_count}}
_class_cache: Dict[int, CacheEntry] = {}


def find_objc_classes(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Find Objective-C classes matching a wildcard pattern.
    Lists all registered classes that match the specified pattern.

    Flags:
        --reload: Force cache refresh and reload all classes from runtime
        --clear-cache: Clear the cache for the current process
        --batch-size=N or --batch-size N: Set batch size for class_getName() calls (default: 35)
        --verbose: Show detailed timing breakdown and resource usage
        --ivars: Show instance variables for single class match
        --properties: Show properties for single class match
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the input: [--reload] [--clear-cache] [--batch-size=N] [--verbose] [--ivars] [--properties] [pattern]
    args = command.strip().split()
    force_reload = '--reload' in args
    clear_cache = '--clear-cache' in args
    verbose = '--verbose' in args
    show_ivars = '--ivars' in args
    show_properties = '--properties' in args

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

    # Get pattern, treating empty string as "no pattern" (list all)
    pattern = pattern_args[0] if pattern_args else None
    if pattern == '' or pattern == '""':
        pattern = None

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

    # Display results with hierarchy information based on match count
    num_matches = len(class_names)

    if num_matches == 0:
        print(f"No classes found{f' matching: {pattern}' if pattern else ''}")
    elif num_matches == 1:
        # Exactly 1 match: Show detailed hierarchy view with dylib
        class_name = class_names[0]

        hierarchy = get_class_hierarchy(frame, class_name)
        if hierarchy and len(hierarchy) > 1:
            # Display class name normally, hierarchy in dim gray
            # ANSI escape codes: \033[90m = bright black (dim gray), \033[0m = reset
            hierarchy_str = " → ".join(hierarchy[1:])
            print(f"{class_name} \033[90m→ {hierarchy_str}\033[0m")
        else:
            print(f"{class_name}")

        # Show dylib/framework containing the class
        image_path = get_class_image_path(frame, class_name)
        if image_path:
            # Display the path in dim gray
            print(f"  \033[90m{image_path}\033[0m")

        # Show ivars if --ivars flag is present
        if show_ivars:
            ivars = get_class_ivars(frame, class_name)
            if ivars:
                print(f"\n  Instance Variables ({len(ivars)}):")
                for ivar_name, ivar_type_enc, ivar_offset in ivars:
                    # Decode the type encoding to make it more readable
                    ivar_type = decode_type_encoding(ivar_type_enc)

                    # Format: offset (dim gray, padded) + name (normal) + type (dim gray)
                    # ANSI escape codes: \033[90m = bright black (dim gray), \033[0m = reset
                    if ivar_offset is not None:
                        # Pad offset to 3 hex digits (0x000 format)
                        print(f"    \033[90m0x{ivar_offset:03x}\033[0m  {ivar_name}  \033[90m{ivar_type}\033[0m")
                    else:
                        print(f"    \033[90m     \033[0m  {ivar_name}  \033[90m{ivar_type}\033[0m")
            else:
                print(f"\n  Instance Variables: none")

        # Show properties if --properties flag is present
        if show_properties:
            properties = get_class_properties(frame, class_name)
            if properties:
                print(f"\n  Properties ({len(properties)}):")
                for prop_name, prop_attrs in properties:
                    # Parse attributes to make them more readable
                    type_str, attrs_list, ivar_name = parse_property_attributes(prop_attrs)

                    # Format: name (normal) + type and attributes (dim gray)
                    # ANSI escape codes: \033[90m = bright black (dim gray), \033[0m = reset
                    if attrs_list:
                        attrs_str = ', '.join(attrs_list)
                        print(f"    {prop_name} \033[90m{type_str} ({attrs_str})\033[0m")
                    else:
                        print(f"    {prop_name} \033[90m{type_str}\033[0m")
            else:
                print(f"\n  Properties: none")

    elif num_matches <= 20:
        # 2-20 matches: Show compact one-liner with hierarchy for each
        print(f"Found {num_matches} class(es){f' matching: {pattern}' if pattern else ''}:")
        for class_name in sorted(class_names):
            hierarchy = get_class_hierarchy(frame, class_name)
            if hierarchy and len(hierarchy) > 1:
                # Display class name normally, hierarchy in dim gray
                # ANSI escape codes: \033[90m = bright black (dim gray), \033[0m = reset
                hierarchy_str = " → ".join(hierarchy[1:])
                print(f"  {hierarchy[0]} \033[90m→ {hierarchy_str}\033[0m")
            else:
                print(f"  {class_name}")
    else:
        # More than 20 matches: Just list class names (current behavior)
        print(f"Found {num_matches} class(es){f' matching: {pattern}' if pattern else ''}:")
        for class_name in sorted(class_names):
            print(f"  {class_name}")

    # Print timing metrics only when wildcards are involved or listing all classes
    # (no point showing metrics for exact single class match via fast-path)
    has_wildcards = pattern and ('*' in pattern or '?' in pattern)
    show_metrics = verbose or has_wildcards or pattern is None

    if show_metrics:
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

def get_class_image_path(frame: lldb.SBFrame, class_name: str) -> Optional[str]:
    """
    Get the path to the dylib/framework containing a class.

    Uses class_getImageName() to get the image path for the class.

    Args:
        frame: LLDB frame for expression evaluation
        class_name: Name of the class to look up

    Returns:
        Path to the image (dylib/framework) containing the class, or None on error
    """
    # Get the class object
    class_expr = f'(void *)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return None

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return None

    # Get the image name using class_getImageName
    image_expr = f'(const char *)class_getImageName((Class)0x{class_ptr:x})'
    image_result = frame.EvaluateExpression(image_expr)

    if not image_result.IsValid() or image_result.GetError().Fail():
        return None

    image_path = image_result.GetSummary()
    if image_path:
        image_path = unquote_string(image_path)
        return image_path

    return None


def get_class_hierarchy(frame: lldb.SBFrame, class_name: str) -> List[str]:
    """
    Get the inheritance hierarchy for a class.
    Returns a list of class names from the given class up to the root (e.g., NSObject).

    Args:
        frame: LLDB frame for expression evaluation
        class_name: Name of the class to get hierarchy for

    Returns:
        List of class names in hierarchy order [ClassName, SuperClass, ..., NSObject]
        Returns empty list on error
    """
    hierarchy = []

    # Get the class object
    class_expr = f'(void *)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return []

    current_class = class_result.GetValueAsUnsigned()
    if current_class == 0:
        return []

    # Walk up the superclass chain
    max_depth = 20  # Prevent infinite loops
    for _ in range(max_depth):
        # Get current class name
        name_expr = f'(const char *)class_getName((void *)0x{current_class:x})'
        name_result = frame.EvaluateExpression(name_expr)

        if not name_result.IsValid() or name_result.GetError().Fail():
            break

        current_name = name_result.GetSummary()
        if current_name:
            current_name = unquote_string(current_name)
            hierarchy.append(current_name)
        else:
            break

        # Get superclass
        super_expr = f'(void *)class_getSuperclass((void *)0x{current_class:x})'
        super_result = frame.EvaluateExpression(super_expr)

        if not super_result.IsValid() or super_result.GetError().Fail():
            break

        current_class = super_result.GetValueAsUnsigned()
        if current_class == 0:
            break

    return hierarchy


def get_class_ivars(frame: lldb.SBFrame, class_name: str) -> List[Dict[str, str]]:
    """
    Get the instance variables for a class.

    Optimized implementation using batch pointer fetch + memory reads:
    - Single expression to fetch all ivar name/type/offset pointers at once
    - Uses process.ReadCStringFromMemory to read strings from those pointers
    - Reduces expression count from 3N+5 to 6 (for N ivars)
    - For 91 ivars: ~273 expressions → ~6 expressions (45x reduction in expression count)
    - Actual performance: ~1.8s (limited by expression parsing overhead for large batches)

    Args:
        frame: LLDB frame for expression evaluation
        class_name: Name of the class to get ivars for

    Returns:
        List of tuples (ivar_name, ivar_type, ivar_offset) or empty list on error
    """
    ivars = []

    # Get the class object
    class_expr = f'(void *)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return []

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return []

    # We need to allocate memory for the count
    count_var_expr = f'(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        return []

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Get ivar list
    ivar_list_expr = f'(void *)class_copyIvarList((Class)0x{class_ptr:x}, (unsigned int *)0x{count_var_ptr:x})'
    ivar_list_result = frame.EvaluateExpression(ivar_list_expr)

    if not ivar_list_result.IsValid() or ivar_list_result.GetError().Fail():
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    ivar_list_ptr = ivar_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        if ivar_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{ivar_list_ptr:x})')
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    ivar_count = count_read_result.GetValueAsUnsigned()

    if ivar_count == 0 or ivar_list_ptr == 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    # Read ivar list as array of pointers
    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()
    array_size = ivar_count * pointer_size

    error = lldb.SBError()
    ivar_array_bytes = process.ReadMemory(ivar_list_ptr, array_size, error)

    if not error.Success():
        if ivar_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{ivar_list_ptr:x})')
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    # Parse ivar pointers
    if pointer_size == 8:
        format_str = f'{ivar_count}Q'
    else:
        format_str = f'{ivar_count}I'

    ivar_pointers = struct.unpack(format_str, ivar_array_bytes)

    # OPTIMIZATION: Batch expression to get all pointers at once, then bulk memory reads
    # Strategy: Single expression returns struct with all name/type/offset pointers
    # Then use fast memory reads to get the actual strings

    # Build a batched expression that gets all info for all ivars at once
    info_struct_size = ivar_count * 3 * 8  # 3 pointers per ivar (name, type, offset as ptr)

    batch_expr = f'''
(void *)(^{{
    void **info = (void **)malloc({info_struct_size});
    if (!info) return (void *)0;
    '''

    for i, ivar_ptr in enumerate(ivar_pointers):
        if ivar_ptr != 0:
            batch_expr += f'''
    info[{i * 3}] = (void *)ivar_getName((void *)0x{ivar_ptr:x});
    info[{i * 3 + 1}] = (void *)ivar_getTypeEncoding((void *)0x{ivar_ptr:x});
    info[{i * 3 + 2}] = (void *)ivar_getOffset((void *)0x{ivar_ptr:x});
'''
        else:
            batch_expr += f'''
    info[{i * 3}] = (void *)0;
    info[{i * 3 + 1}] = (void *)0;
    info[{i * 3 + 2}] = (void *)0;
'''

    batch_expr += '''
    return (void *)info;
}())
'''

    # Execute the batch expression
    batch_result = frame.EvaluateExpression(batch_expr)

    if batch_result.IsValid() and not batch_result.GetError().Fail():
        info_ptr = batch_result.GetValueAsUnsigned()

        if info_ptr != 0:
            # Read the entire info struct in one memory read
            error = lldb.SBError()
            info_bytes = process.ReadMemory(info_ptr, info_struct_size, error)

            if error.Success():
                # Parse the pointers
                if pointer_size == 8:
                    info_pointers = struct.unpack(f'{ivar_count * 3}Q', info_bytes)
                else:
                    info_pointers = struct.unpack(f'{ivar_count * 3}I', info_bytes)

                # Now read strings from memory using the pointers
                for i in range(ivar_count):
                    name_ptr = info_pointers[i * 3]
                    type_ptr = info_pointers[i * 3 + 1]
                    offset_val = info_pointers[i * 3 + 2]

                    if name_ptr == 0:
                        continue

                    # Read name string from memory
                    ivar_name = process.ReadCStringFromMemory(name_ptr, 256, error)
                    if not error.Success() or not ivar_name:
                        continue

                    # Read type string from memory
                    if type_ptr == 0:
                        ivar_type = "?"
                    else:
                        ivar_type = process.ReadCStringFromMemory(type_ptr, 256, error)
                        if not error.Success() or not ivar_type:
                            ivar_type = "?"

                    # offset_val is already the offset (stored as pointer-sized value)
                    ivar_offset = offset_val if offset_val != 0 else None

                    ivars.append((ivar_name, ivar_type, ivar_offset))

            # Free the info struct
            frame.EvaluateExpression(f'(void)free((void *)0x{info_ptr:x})')
    else:
        # Fallback to individual calls
        for ivar_ptr in ivar_pointers:
            if ivar_ptr == 0:
                continue

            # Get ivar name
            name_expr = f'(const char *)ivar_getName((void *)0x{ivar_ptr:x})'
            name_result = frame.EvaluateExpression(name_expr)

            if not name_result.IsValid() or name_result.GetError().Fail():
                continue

            ivar_name = name_result.GetSummary()
            if ivar_name:
                # Remove outer quotes (exactly one from each end)
                if ivar_name.startswith('"') and ivar_name.endswith('"'):
                    ivar_name = ivar_name[1:-1]
            else:
                continue

            # Get ivar type encoding
            type_expr = f'(const char *)ivar_getTypeEncoding((void *)0x{ivar_ptr:x})'
            type_result = frame.EvaluateExpression(type_expr)

            if not type_result.IsValid() or type_result.GetError().Fail():
                ivar_type = "?"
            else:
                ivar_type = type_result.GetSummary()
                if ivar_type:
                    # Remove outer quotes (exactly one from each end) and unescape internal quotes
                    # Note: Don't use strip('"') - it removes ALL consecutive quotes, corrupting
                    # strings like "@\"NSString\"" where the trailing "" gets fully stripped
                    if ivar_type.startswith('"') and ivar_type.endswith('"'):
                        ivar_type = ivar_type[1:-1]
                    ivar_type = ivar_type.replace('\\"', '"')
                else:
                    ivar_type = "?"

            # Get ivar offset
            offset_expr = f'(ptrdiff_t)ivar_getOffset((void *)0x{ivar_ptr:x})'
            offset_result = frame.EvaluateExpression(offset_expr)

            if not offset_result.IsValid() or offset_result.GetError().Fail():
                ivar_offset = None
            else:
                ivar_offset = offset_result.GetValueAsSigned()

            ivars.append((ivar_name, ivar_type, ivar_offset))

    # Clean up
    if ivar_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{ivar_list_ptr:x})')
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')

    return ivars


def parse_property_attributes(attr_string: str) -> Dict[str, Any]:
    """
    Parse Objective-C property attribute string into human-readable format.

    Property attribute encoding format:
        T<type>,<attribute>,<attribute>,...

    Common attributes:
        T<type>     - Type encoding
        V<name>     - Instance variable name
        R           - readonly
        C           - copy
        &           - retain
        N           - nonatomic
        D           - dynamic
        W           - weak
        P           - eligible for garbage collection (legacy)
        G<name>     - Custom getter (name)
        S<name>     - Custom setter (name)

    Args:
        attr_string: Raw property attribute string (e.g., "T@\"NSString\",R,N,V_name")

    Returns:
        Tuple of (type_string, attributes_list)
    """
    if not attr_string:
        return ("?", [])

    # Split by comma
    parts = attr_string.split(',')

    type_string = "?"
    attributes = []
    ivar_name = None
    getter_name = None
    setter_name = None

    for part in parts:
        if not part:
            continue

        if part.startswith('T'):
            # Type encoding
            type_enc = part[1:]
            type_string = decode_type_encoding(type_enc)
        elif part.startswith('V'):
            # Instance variable name
            ivar_name = part[1:]
        elif part.startswith('G'):
            # Custom getter
            getter_name = part[1:]
        elif part.startswith('S'):
            # Custom setter
            setter_name = part[1:]
        elif part == 'R':
            attributes.append('readonly')
        elif part == 'C':
            attributes.append('copy')
        elif part == '&':
            attributes.append('strong')
        elif part == 'N':
            attributes.append('nonatomic')
        elif part == 'D':
            attributes.append('dynamic')
        elif part == 'W':
            attributes.append('weak')

    # Add custom getter/setter if present
    if getter_name:
        attributes.append(f'getter={getter_name}')
    if setter_name:
        attributes.append(f'setter={setter_name}')

    return (type_string, attributes, ivar_name)


def decode_type_encoding(type_enc: str) -> str:
    """
    Decode Objective-C type encoding into human-readable type.

    Common type encodings:
        c - char
        i - int
        s - short
        l - long
        q - long long
        C - unsigned char
        I - unsigned int
        S - unsigned short
        L - unsigned long
        Q - unsigned long long
        f - float
        d - double
        B - bool / _Bool
        v - void
        * - char *
        @ - id (object)
        @"ClassName" - Class instance
        # - Class
        : - SEL
        ^ - pointer
        ? - unknown / function pointer
        [n<type>] - array
        {name=...} - struct
        (name=...) - union
        b<num> - bitfield
        r - const (qualifier)
        n - in (qualifier)
        N - inout (qualifier)
        o - out (qualifier)
        O - bycopy (qualifier)
        R - byref (qualifier)
        V - oneway (qualifier)

    Args:
        type_enc: Type encoding string

    Returns:
        Human-readable type string
    """
    if not type_enc:
        return "?"

    # Strip type qualifiers (r, n, N, o, O, R, V)
    qualifiers = []
    while type_enc and type_enc[0] in 'rnNoORV':
        qual = type_enc[0]
        if qual == 'r':
            qualifiers.append('const')
        elif qual == 'n':
            qualifiers.append('in')
        elif qual == 'N':
            qualifiers.append('inout')
        elif qual == 'o':
            qualifiers.append('out')
        elif qual == 'O':
            qualifiers.append('bycopy')
        elif qual == 'R':
            qualifiers.append('byref')
        elif qual == 'V':
            qualifiers.append('oneway')
        type_enc = type_enc[1:]

    # Object type with class name: @"ClassName" or @"ClassName"
    # Handle various quote formats that may come from runtime
    if type_enc.startswith('@"') or type_enc.startswith('@\\"'):
        # Find the class name between quotes
        # Handle both @"ClassName" and @\"ClassName\" formats
        if type_enc.startswith('@\\"'):
            # Escaped quotes format: @\"ClassName\"
            start_idx = 3
            # Find closing escaped quote
            end_idx = type_enc.find('\\"', start_idx)
            if end_idx == -1:
                end_idx = type_enc.find('"', start_idx)
            if end_idx == -1:
                end_idx = len(type_enc)
        else:
            # Normal quotes format: @"ClassName"
            start_idx = 2
            # Find closing quote
            end_idx = type_enc.rfind('"')
            if end_idx <= start_idx:
                end_idx = len(type_enc)

        class_name = type_enc[start_idx:end_idx]

        # Strip angle brackets for protocols
        if class_name.startswith('<') and class_name.endswith('>'):
            protocol_name = class_name[1:-1]
            result = f"id<{protocol_name}>"
        else:
            result = class_name

        if qualifiers:
            return f"{' '.join(qualifiers)} {result}"
        return result

    # Basic types
    type_map = {
        'c': 'char',
        'i': 'int',
        's': 'short',
        'l': 'long',
        'q': 'long long',
        'C': 'unsigned char',
        'I': 'unsigned int',
        'S': 'unsigned short',
        'L': 'unsigned long',
        'Q': 'unsigned long long',
        'f': 'float',
        'd': 'double',
        'B': 'BOOL',
        'v': 'void',
        '*': 'char *',
        '@': 'id',
        '@?': 'block',
        '#': 'Class',
        ':': 'SEL',
        '?': '?'
    }

    # Check basic types first
    if type_enc in type_map:
        result = type_map[type_enc]
        if qualifiers:
            return f"{' '.join(qualifiers)} {result}"
        return result

    # Pointer type
    if type_enc.startswith('^'):
        base_type = decode_type_encoding(type_enc[1:])
        result = f"{base_type} *"
        if qualifiers:
            return f"{' '.join(qualifiers)} {result}"
        return result

    # Array type
    if type_enc.startswith('['):
        # Format: [count<type>]
        end_bracket = type_enc.find(']')
        if end_bracket > 0:
            inner = type_enc[1:end_bracket]
            # Extract count
            count_end = 0
            while count_end < len(inner) and inner[count_end].isdigit():
                count_end += 1
            if count_end > 0:
                count = inner[:count_end]
                elem_type = decode_type_encoding(inner[count_end:])
                result = f"{elem_type}[{count}]"
                if qualifiers:
                    return f"{' '.join(qualifiers)} {result}"
                return result

    # Struct type
    if type_enc.startswith('{'):
        # Format: {name=field1field2...}
        # Just extract the struct name
        end_equal = type_enc.find('=')
        if end_equal > 0:
            struct_name = type_enc[1:end_equal]
            result = f"struct {struct_name}"
        else:
            end_brace = type_enc.find('}')
            if end_brace > 0:
                struct_name = type_enc[1:end_brace]
                result = f"struct {struct_name}"
            else:
                result = type_enc
        if qualifiers:
            return f"{' '.join(qualifiers)} {result}"
        return result

    # Union type
    if type_enc.startswith('('):
        # Format: (name=field1field2...)
        end_equal = type_enc.find('=')
        if end_equal > 0:
            union_name = type_enc[1:end_equal]
            result = f"union {union_name}"
            if qualifiers:
                return f"{' '.join(qualifiers)} {result}"
            return result

    # Bitfield
    if type_enc.startswith('b'):
        # Format: b<num>
        num = type_enc[1:]
        bit_label = "bit" if num == "1" else "bits"
        result = f"{num} {bit_label}"
        if qualifiers:
            return f"{' '.join(qualifiers)} {result}"
        return result

    # Unknown - return as-is
    if qualifiers:
        return f"{' '.join(qualifiers)} {type_enc}"
    return type_enc


def get_class_properties(frame: lldb.SBFrame, class_name: str) -> List[Dict[str, Any]]:
    """
    Get the properties for a class.

    Optimized implementation using batch pointer fetch + memory reads:
    - Single expression to fetch all property name/attributes pointers at once
    - Uses process.ReadCStringFromMemory to read strings from those pointers
    - Reduces expression count from 2N+5 to 6 (for N properties)
    - For 95 properties: ~190 expressions → ~6 expressions (31x reduction in expression count)
    - Actual performance: ~1.2s (limited by expression parsing overhead for large batches)

    Args:
        frame: LLDB frame for expression evaluation
        class_name: Name of the class to get properties for

    Returns:
        List of tuples (property_name, property_attributes) or empty list on error
    """
    import struct

    properties = []

    # Get the class object
    class_expr = f'(void *)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return []

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return []

    # Allocate memory for the count
    count_var_expr = f'(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        return []

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Get property list
    prop_list_expr = f'(void *)class_copyPropertyList((Class)0x{class_ptr:x}, (unsigned int *)0x{count_var_ptr:x})'
    prop_list_result = frame.EvaluateExpression(prop_list_expr)

    if not prop_list_result.IsValid() or prop_list_result.GetError().Fail():
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    prop_list_ptr = prop_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        if prop_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{prop_list_ptr:x})')
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    prop_count = count_read_result.GetValueAsUnsigned()

    if prop_count == 0 or prop_list_ptr == 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    # Read property list as array of pointers
    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()
    array_size = prop_count * pointer_size

    error = lldb.SBError()
    prop_array_bytes = process.ReadMemory(prop_list_ptr, array_size, error)

    if not error.Success():
        if prop_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{prop_list_ptr:x})')
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    # Parse property pointers
    if pointer_size == 8:
        format_str = f'{prop_count}Q'
    else:
        format_str = f'{prop_count}I'

    prop_pointers = struct.unpack(format_str, prop_array_bytes)

    # OPTIMIZATION: Batch expression to get all pointers at once, then bulk memory reads
    # Strategy: Single expression returns struct with all name/attr pointers
    # Then use fast memory reads to get the actual strings

    # Build a batched expression that gets all info for all properties at once
    info_struct_size = prop_count * 2 * 8  # 2 pointers per property (name, attributes)

    batch_expr = f'''
(void *)(^{{
    void **info = (void **)malloc({info_struct_size});
    if (!info) return (void *)0;
    '''

    for i, prop_ptr in enumerate(prop_pointers):
        if prop_ptr != 0:
            batch_expr += f'''
    info[{i * 2}] = (void *)property_getName((void *)0x{prop_ptr:x});
    info[{i * 2 + 1}] = (void *)property_getAttributes((void *)0x{prop_ptr:x});
'''
        else:
            batch_expr += f'''
    info[{i * 2}] = (void *)0;
    info[{i * 2 + 1}] = (void *)0;
'''

    batch_expr += '''
    return (void *)info;
}())
'''

    # Execute the batch expression
    batch_result = frame.EvaluateExpression(batch_expr)

    if batch_result.IsValid() and not batch_result.GetError().Fail():
        info_ptr = batch_result.GetValueAsUnsigned()

        if info_ptr != 0:
            # Read the entire info struct in one memory read
            error = lldb.SBError()
            info_bytes = process.ReadMemory(info_ptr, info_struct_size, error)

            if error.Success():
                # Parse the pointers
                if pointer_size == 8:
                    info_pointers = struct.unpack(f'{prop_count * 2}Q', info_bytes)
                else:
                    info_pointers = struct.unpack(f'{prop_count * 2}I', info_bytes)

                # Now read strings from memory using the pointers
                for i in range(prop_count):
                    name_ptr = info_pointers[i * 2]
                    attr_ptr = info_pointers[i * 2 + 1]

                    if name_ptr == 0:
                        continue

                    # Read name string from memory
                    prop_name = process.ReadCStringFromMemory(name_ptr, 256, error)
                    if not error.Success() or not prop_name:
                        continue

                    # Read attributes string from memory
                    if attr_ptr == 0:
                        prop_attrs = ""
                    else:
                        prop_attrs = process.ReadCStringFromMemory(attr_ptr, 512, error)
                        if not error.Success() or not prop_attrs:
                            prop_attrs = ""

                    properties.append((prop_name, prop_attrs))

            # Free the info struct
            frame.EvaluateExpression(f'(void)free((void *)0x{info_ptr:x})')
    else:
        # Fallback to individual calls
        for prop_ptr in prop_pointers:
            if prop_ptr == 0:
                continue

            # Get property name
            name_expr = f'(const char *)property_getName((void *)0x{prop_ptr:x})'
            name_result = frame.EvaluateExpression(name_expr)

            if not name_result.IsValid() or name_result.GetError().Fail():
                continue

            prop_name = name_result.GetSummary()
            if prop_name:
                # Remove outer quotes (exactly one from each end)
                if prop_name.startswith('"') and prop_name.endswith('"'):
                    prop_name = prop_name[1:-1]
            else:
                continue

            # Get property attributes
            attr_expr = f'(const char *)property_getAttributes((void *)0x{prop_ptr:x})'
            attr_result = frame.EvaluateExpression(attr_expr)

            if not attr_result.IsValid() or attr_result.GetError().Fail():
                prop_attrs = ""
            else:
                prop_attrs = attr_result.GetSummary()
                if prop_attrs:
                    # Remove outer quotes (exactly one from each end) and unescape internal quotes
                    # Note: Don't use strip('"') - it removes ALL consecutive quotes
                    if prop_attrs.startswith('"') and prop_attrs.endswith('"'):
                        prop_attrs = prop_attrs[1:-1]
                    prop_attrs = prop_attrs.replace('\\"', '"')
                else:
                    prop_attrs = ""

            properties.append((prop_name, prop_attrs))

    # Clean up
    if prop_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{prop_list_ptr:x})')
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')

    return properties


def matches_pattern(class_name: str, pattern: Optional[str]) -> bool:
    """
    Check if class name matches the pattern.
    Supports wildcards: * (any characters) and ? (single character)
    Without wildcards: exact match (case-sensitive)
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
            # Fallback to exact match if regex is invalid
            return class_name == pattern
    else:
        # Exact matching (case-sensitive)
        return class_name == pattern

def build_batch_expression(class_pointers_batch: List[int]) -> str:
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


def read_consolidated_string_buffer(
    batch_result: lldb.SBValue,
    batch_size: int,
    process: lldb.SBProcess,
    frame: lldb.SBFrame,
    pattern: Optional[str] = None
) -> List[str]:
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


def try_exact_class_match(
    frame: lldb.SBFrame,
    class_name: str
) -> Tuple[Optional[str], Optional[TimingDict]]:
    """
    Fast-path: Try to match a specific class name directly using NSClassFromString.

    Args:
        frame: LLDB frame for expression evaluation
        class_name: Exact class name to look up

    Returns:
        Tuple of (class_name, timing_dict) if found, (None, None) otherwise
    """
    start_time = time.time()

    # Try to get the class directly
    class_expr = f'(void *)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return None, None

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return None, None

    # Verify the class name matches (in case of partial match)
    name_expr = f'(const char *)class_getName((void *)0x{class_ptr:x})'
    name_result = frame.EvaluateExpression(name_expr)

    if not name_result.IsValid() or name_result.GetError().Fail():
        return None, None

    actual_name = name_result.GetSummary()
    if actual_name:
        actual_name = unquote_string(actual_name)
        if actual_name == class_name:
            timing = {
                'total': time.time() - start_time,
                'setup': 0,
                'bulk_read': 0,
                'batching': 0,
                'cleanup': 0,
                'expression_count': 2,
                'memory_read_count': 0
            }
            return actual_name, timing

    return None, None


def get_all_classes(
    frame: lldb.SBFrame,
    pattern: Optional[str] = None,
    force_reload: bool = False,
    batch_size: Optional[int] = None
) -> Tuple[List[str], TimingDict, int, bool]:
    """
    Get all Objective-C classes using objc_copyClassList.
    Returns a list of class names matching the pattern.

    Optimized implementation using consolidated string buffers:
    - Batches class_getName() calls into configurable groups
    - Consolidates string data into single buffers
    - Reduces expression evaluations from ~10K to ~100
    - Reduces memory reads from ~10K to ~200
    - Caches results per-process for instant subsequent queries
    - Fast-path for exact matches (bypasses full enumeration)

    For 10,000 classes:
    - Fast-path (exact match): <0.01 seconds
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

    process = frame.GetThread().GetProcess()
    pid = process.GetProcessID()

    start_time = time.time()

    # FAST-PATH: If pattern doesn't contain wildcards, try exact match first
    if pattern and '*' not in pattern and '?' not in pattern:
        exact_match, exact_timing = try_exact_class_match(frame, pattern)
        if exact_match:
            # Return immediately with the exact match
            return [exact_match], exact_timing, 1, False
        else:
            # Class not found - return empty results immediately
            # No point enumerating all classes for an exact match that doesn't exist
            timing = {
                'total': time.time() - start_time,
                'setup': 0,
                'bulk_read': 0,
                'batching': 0,
                'cleanup': 0,
                'expression_count': exact_timing['expression_count'] if exact_timing else 2,
                'memory_read_count': 0
            }
            return [], timing, 0, False

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
                        class_name = unquote_string(class_name)
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


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Find Objective-C classes. '
        'Usage: ocls [pattern] [--reload] [--clear-cache] [--verbose]" '
        '-f objc_cls.find_objc_classes ocls'
    )
    print(f"[lldb-objc v{__version__}] Objective-C class finder command 'ocls' has been installed.")
    print("Usage: ocls [pattern]")
