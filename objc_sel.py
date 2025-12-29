#!/usr/bin/env python3
"""
LLDB script for finding selectors in Objective-C classes.

Usage:
    osel ClassName [options] [pattern]
    osel ClassName           # List all selectors
    osel ClassName service   # Find selectors containing 'service'
    osel ClassName *ternal   # Find selectors ending with 'ternal' (wildcard)
    osel ClassName _init*    # Find selectors starting with '_init' (wildcard)
    osel ClassName *set*     # Find selectors containing 'set' anywhere (wildcard)

Options:
    --reload       Force reload methods from runtime (bypass cache)
    --clear-cache  Clear cache for current process
    --verbose      Show detailed timing breakdown and resource usage
    --instance     Show only instance methods (-)
    --class        Show only class methods (+)

Pattern matching:
  - Simple text: substring match (case-insensitive)
  - With *: matches any sequence of characters
  - With ?: matches any single character

Performance:
  - Optimized using batched expression evaluation
  - Per-class method caching for instant subsequent queries
  - Use --reload to refresh cache when runtime state changes
"""

from __future__ import annotations

import lldb
import os
import re
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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

# Configurable batch size for selector name retrieval
# Smaller than ocls because selector expressions are simpler
DEFAULT_BATCH_SIZE = 50

# Global cache for selector lists
# Structure: {process_id: {class_name: {'instance': [(sel_name, imp_addr), ...], 'class': [...], 'timestamp': time}}}
_selector_cache: Dict[int, Dict[str, CacheEntry]] = {}


def find_objc_selectors(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Find selectors in an Objective-C class.
    Lists both instance and class methods, optionally filtered by pattern.

    Flags:
        --reload: Force cache refresh and reload methods from runtime
        --clear-cache: Clear the cache for the current process
        --verbose: Show detailed timing breakdown and resource usage
        --instance: Show only instance methods
        --class: Show only class methods
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the input: ClassName [--reload] [--clear-cache] [--verbose] [--instance] [--class] [pattern]
    args = command.strip().split()
    force_reload = '--reload' in args
    clear_cache = '--clear-cache' in args
    verbose = '--verbose' in args
    instance_only = '--instance' in args
    class_only = '--class' in args

    # Remove flags from args
    non_flag_args = [arg for arg in args if not arg.startswith('--')]

    if len(non_flag_args) < 1:
        # Handle --clear-cache without class name
        if clear_cache:
            pid = process.GetProcessID()
            if pid in _selector_cache:
                del _selector_cache[pid]
                print("Selector cache cleared for current process")
            else:
                print("No selector cache found for current process")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return
        result.SetError("Usage: osel ClassName [--reload] [--clear-cache] [--verbose] [--instance] [--class] [pattern]")
        return

    class_name = non_flag_args[0]
    pattern = non_flag_args[1] if len(non_flag_args) > 1 else None

    # Handle cache clearing for specific class
    pid = process.GetProcessID()
    if clear_cache:
        if pid in _selector_cache and class_name in _selector_cache[pid]:
            del _selector_cache[pid][class_name]
            print(f"Cache cleared for class '{class_name}'")
        else:
            print(f"No cache found for class '{class_name}'")
        if not pattern and not force_reload:
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

    print(f"Searching for selectors in class: {class_name}")
    if pattern:
        print(f"Filter pattern: {pattern}")

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Initialize timing
    start_time = time.time()
    timing = {
        'total': 0,
        'setup': 0,
        'instance_methods': 0,
        'class_methods': 0,
        'expression_count': 0,
        'memory_read_count': 0
    }

    setup_start = time.time()

    # Check cache first
    from_cache = False
    if not force_reload and pid in _selector_cache and class_name in _selector_cache[pid]:
        cache_entry = _selector_cache[pid][class_name]
        all_instance_methods = cache_entry['instance']
        all_class_methods = cache_entry['class']

        # Filter by pattern (now methods are tuples of (sel_name, imp_addr))
        if pattern:
            instance_methods = [(name, addr) for name, addr in all_instance_methods if matches_pattern(name, pattern)]
            class_methods = [(name, addr) for name, addr in all_class_methods if matches_pattern(name, pattern)]
        else:
            instance_methods = all_instance_methods
            class_methods = all_class_methods

        from_cache = True
        timing['total'] = time.time() - start_time
    else:
        # Get the class using NSClassFromString
        class_expr = f'(Class)NSClassFromString(@"{class_name}")'
        class_result = frame.EvaluateExpression(class_expr)
        timing['expression_count'] += 1

        if not class_result.IsValid() or class_result.GetError().Fail():
            result.SetError(f"Failed to resolve class '{class_name}': {class_result.GetError()}")
            return

        class_ptr = class_result.GetValueAsUnsigned()

        if class_ptr == 0:
            result.SetError(f"Class '{class_name}' not found")
            return

        print(f"Class pointer: {class_result.GetValue()}")

        timing['setup'] = time.time() - setup_start

        # Find instance methods (unless --class flag is set)
        instance_start = time.time()
        if not class_only:
            all_instance_methods, inst_timing = get_methods_optimized(frame, process, class_ptr, is_instance=True)
            timing['expression_count'] += inst_timing['expression_count']
            timing['memory_read_count'] += inst_timing['memory_read_count']
        else:
            all_instance_methods = []
            inst_timing = {'expression_count': 0, 'memory_read_count': 0}
        timing['instance_methods'] = time.time() - instance_start

        # Get metaclass for class methods (unless --instance flag is set)
        class_start = time.time()
        if not instance_only:
            metaclass_expr = f'(Class)object_getClass((id)0x{class_ptr:x})'
            metaclass_result = frame.EvaluateExpression(metaclass_expr)
            timing['expression_count'] += 1

            if metaclass_result.IsValid() and not metaclass_result.GetError().Fail():
                metaclass_ptr = metaclass_result.GetValueAsUnsigned()
                all_class_methods, cls_timing = get_methods_optimized(frame, process, metaclass_ptr, is_instance=False)
                timing['expression_count'] += cls_timing['expression_count']
                timing['memory_read_count'] += cls_timing['memory_read_count']
            else:
                all_class_methods = []
        else:
            all_class_methods = []
        timing['class_methods'] = time.time() - class_start

        timing['total'] = time.time() - start_time

        # Store in cache (unfiltered lists)
        if pid not in _selector_cache:
            _selector_cache[pid] = {}
        _selector_cache[pid][class_name] = {
            'instance': all_instance_methods,
            'class': all_class_methods,
            'timestamp': time.time()
        }

        # Apply pattern filter (methods are now tuples of (sel_name, imp_addr))
        if pattern:
            instance_methods = [(name, addr) for name, addr in all_instance_methods if matches_pattern(name, pattern)]
            class_methods = [(name, addr) for name, addr in all_class_methods if matches_pattern(name, pattern)]
        else:
            instance_methods = all_instance_methods
            class_methods = all_class_methods

    # Display results
    print()

    # Show instance methods unless --class flag is set
    if not class_only:
        if instance_methods:
            print(f"Instance methods ({len(instance_methods)}):")
            for sel_name, imp_addr in sorted(instance_methods, key=lambda x: x[0]):
                # Display address in dimmed gray text
                if imp_addr:
                    print(f"  -{sel_name}  \033[90m0x{imp_addr:x}\033[0m")
                else:
                    print(f"  -{sel_name}")
        else:
            print("No instance methods found")

    # Show class methods unless --instance flag is set
    if not instance_only:
        if class_methods:
            if not class_only:
                print()  # Extra newline between sections
            print(f"Class methods ({len(class_methods)}):")
            for sel_name, imp_addr in sorted(class_methods, key=lambda x: x[0]):
                # Display address in dimmed gray text
                if imp_addr:
                    print(f"  +{sel_name}  \033[90m0x{imp_addr:x}\033[0m")
                else:
                    print(f"  +{sel_name}")
        else:
            if not class_only:
                print()
            print("No class methods found")

    total = len(instance_methods) + len(class_methods)
    total_unfiltered = len(all_instance_methods) + len(all_class_methods)
    print(f"\nTotal: {total} method(s)")

    # Print timing metrics
    if verbose:
        print()
        print(f"{'─' * 70}")
        if from_cache:
            print(f"Performance Summary: (from cache)")
            print(f"  Total time:     {timing['total']:.3f}s")
            print(f"  Methods:        {total_unfiltered:,} total, {total:,} matched")
            print(f"  Source:         Cached (use --reload to refresh)")
        else:
            print(f"Performance Summary:")
            print(f"  Total time:     {timing['total']:.2f}s")
            print(f"  Methods:        {total_unfiltered:,} total, {total:,} matched")
            if timing['total'] > 0:
                print(f"  Throughput:     {total_unfiltered / timing['total']:.0f} methods/sec")
            print(f"\n  Timing breakdown:")
            print(f"    Setup:            {timing['setup']:.3f}s")
            print(f"    Instance methods: {timing['instance_methods']:.3f}s")
            print(f"    Class methods:    {timing['class_methods']:.3f}s")
            print(f"\n  Resource usage:")
            print(f"    Expressions:  {timing['expression_count']:,}")
            print(f"    Memory reads: {timing['memory_read_count']:,}")
        print(f"{'─' * 70}")
    else:
        # Compact timing for non-verbose mode
        if from_cache:
            print(f"\n[{total_unfiltered:,} total | {total:,} matched | {timing['total']:.3f}s | cached]")
        else:
            print(f"\n[{total_unfiltered:,} total | {total:,} matched | {timing['total']:.2f}s]")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def matches_pattern(selector_name: str, pattern: Optional[str]) -> bool:
    """
    Check if selector name matches the pattern.
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
            return bool(re.match(regex_pattern, selector_name, re.IGNORECASE))
        except re.error:
            # Fallback to substring match if regex is invalid
            return pattern.lower() in selector_name.lower()
    else:
        # Simple substring matching (case-insensitive)
        return pattern.lower() in selector_name.lower()

def build_selector_batch_expression(method_pointers: Tuple[int, ...]) -> str:
    """
    Build a compound expression that calls sel_getName(method_getName()) and
    method_getImplementation() for multiple methods.

    Args:
        method_pointers: List of method pointer addresses

    Returns:
        String containing the compound expression

    The returned buffer format is:
        Array of (batch_size * 2) pointers:
        - Even indices: selector name pointers
        - Odd indices: IMP addresses
    """
    batch_size = len(method_pointers)

    # Allocate buffer for pointers (batch_size * 2 * pointer_size)
    # Each method needs: selector name pointer + IMP pointer

    # Build expression using Objective-C block
    # Use sizeof(void*) to handle both 32-bit and 64-bit architectures
    expr = f'''
(void *)(^{{
    void **info = (void **)malloc({batch_size * 2} * sizeof(void*));
    if (!info) return (void *)0;
'''

    for i, method_ptr in enumerate(method_pointers):
        if method_ptr != 0:
            expr += f'''
    info[{i * 2}] = (void *)sel_getName((SEL)method_getName((void *)0x{method_ptr:x}));
    info[{i * 2 + 1}] = (void *)method_getImplementation((void *)0x{method_ptr:x});
'''
        else:
            expr += f'''
    info[{i * 2}] = (void *)0;
    info[{i * 2 + 1}] = (void *)0;
'''

    expr += '''
    return (void *)info;
}())
'''

    return expr


def get_methods_optimized(
    frame: lldb.SBFrame,
    process: lldb.SBProcess,
    class_ptr: int,
    is_instance: bool = True
) -> Tuple[List[Tuple[str, int]], TimingDict]:
    """
    Get all methods for a class using class_copyMethodList.
    Returns a tuple of (list of (selector_name, imp_address) tuples, timing dict).

    Optimized implementation using:
    - Bulk memory reads for method pointer array
    - Batched sel_getName(method_getName()) and method_getImplementation() calls
    - process.ReadCStringFromMemory() for fast string retrieval

    For N methods:
    - Before: ~2N expression evaluations
    - After: ~(N/batch_size + 4) expression evaluations + ~(N/batch_size + 1) memory reads
    """
    timing = {
        'expression_count': 0,
        'memory_read_count': 0
    }

    # Allocate space for method count
    count_var_expr = f'(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)
    timing['expression_count'] += 1

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        print(f"Warning: Failed to allocate count variable")
        return [], timing

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Copy method list
    method_list_expr = f'(void *)class_copyMethodList((Class)0x{class_ptr:x}, (unsigned int *)0x{count_var_ptr:x})'
    method_list_result = frame.EvaluateExpression(method_list_expr)
    timing['expression_count'] += 1

    if not method_list_result.IsValid() or method_list_result.GetError().Fail():
        print(f"Warning: class_copyMethodList failed: {method_list_result.GetError()}")
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    method_list_ptr = method_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)
    timing['expression_count'] += 1

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        print(f"Warning: Failed to read method count")
        if method_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    method_count = count_read_result.GetValueAsUnsigned()

    if method_count == 0 or method_list_ptr == 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    # OPTIMIZATION: Bulk read the method pointer array
    pointer_size = frame.GetModule().GetAddressByteSize()
    array_size = method_count * pointer_size

    error = lldb.SBError()
    method_array_bytes = process.ReadMemory(method_list_ptr, array_size, error)
    timing['memory_read_count'] += 1

    if not error.Success():
        print(f"Warning: Failed to read method array from memory: {error}")
        if method_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    # Parse method pointers in Python (fast - no LLDB overhead)
    if pointer_size == 8:
        format_str = f'{method_count}Q'  # 64-bit unsigned pointers
    else:
        format_str = f'{method_count}I'  # 32-bit unsigned pointers

    method_pointers = struct.unpack(format_str, method_array_bytes)

    # OPTIMIZATION: Batch the selector name and IMP retrieval
    selectors = []  # List of (sel_name, imp_addr) tuples
    batch_size = DEFAULT_BATCH_SIZE

    for batch_idx in range(0, len(method_pointers), batch_size):
        batch_end = min(batch_idx + batch_size, len(method_pointers))
        batch = method_pointers[batch_idx:batch_end]
        current_batch_size = len(batch)

        # Build and execute batch expression
        batch_expr = build_selector_batch_expression(batch)
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if not batch_result.IsValid() or batch_result.GetError().Fail():
            # Fallback: process each method individually
            for method_ptr in batch:
                if method_ptr == 0:
                    continue
                # Get selector name
                sel_name_expr = f'(const char *)sel_getName((SEL)method_getName((void *)0x{method_ptr:x}))'
                sel_name_result = frame.EvaluateExpression(sel_name_expr)
                timing['expression_count'] += 1

                # Get IMP
                imp_expr = f'(void *)method_getImplementation((void *)0x{method_ptr:x})'
                imp_result = frame.EvaluateExpression(imp_expr)
                timing['expression_count'] += 1

                if sel_name_result.IsValid() and not sel_name_result.GetError().Fail():
                    sel_name = sel_name_result.GetSummary()
                    if sel_name:
                        sel_name = unquote_string(sel_name)
                        imp_addr = imp_result.GetValueAsUnsigned() if imp_result.IsValid() else 0
                        selectors.append((sel_name, imp_addr))
            continue

        info_ptr = batch_result.GetValueAsUnsigned()
        if info_ptr == 0:
            continue

        # Read the pointer array from memory using correct pointer size
        # Now we have 2 pointers per method: sel_name_ptr and imp_ptr
        ptr_array_size = current_batch_size * 2 * pointer_size
        ptr_bytes = process.ReadMemory(info_ptr, ptr_array_size, error)
        timing['memory_read_count'] += 1

        if error.Success():
            # Parse pointers using correct format for architecture
            ptr_format = f'{current_batch_size * 2}Q' if pointer_size == 8 else f'{current_batch_size * 2}I'
            ptrs = struct.unpack(ptr_format, ptr_bytes)

            # Read each selector name string from memory
            for i in range(current_batch_size):
                sel_ptr = ptrs[i * 2]
                imp_addr = ptrs[i * 2 + 1]

                if sel_ptr == 0:
                    continue

                sel_name = process.ReadCStringFromMemory(sel_ptr, 256, error)
                timing['memory_read_count'] += 1

                if error.Success() and sel_name:
                    selectors.append((sel_name, imp_addr))

        # Free the info buffer
        frame.EvaluateExpression(f'(void)free((void *)0x{info_ptr:x})')
        timing['expression_count'] += 1

    # Clean up allocated memory
    if method_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
        timing['expression_count'] += 1
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
    timing['expression_count'] += 1

    return selectors, timing


def get_methods(
    frame: lldb.SBFrame,
    class_ptr: int,
    is_instance: bool = True,
    pattern: Optional[str] = None
) -> List[str]:
    """
    Get all methods for a class using class_copyMethodList.
    Returns a list of selector names.

    NOTE: This is the legacy unoptimized implementation kept for reference.
    Use get_methods_optimized() for better performance.
    """
    # Allocate space for method count
    count_var_expr = f'(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        print(f"Warning: Failed to allocate count variable")
        return []

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Copy method list
    method_list_expr = f'(void *)class_copyMethodList((Class)0x{class_ptr:x}, (unsigned int *)0x{count_var_ptr:x})'
    method_list_result = frame.EvaluateExpression(method_list_expr)

    if not method_list_result.IsValid() or method_list_result.GetError().Fail():
        print(f"Warning: class_copyMethodList failed: {method_list_result.GetError()}")
        # Clean up
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    method_list_ptr = method_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        print(f"Warning: Failed to read method count")
        # Clean up
        if method_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        return []

    method_count = count_read_result.GetValueAsUnsigned()

    # Collect selector names
    selectors = []
    pointer_size = frame.GetModule().GetAddressByteSize()

    for i in range(method_count):
        # Get method at index
        method_offset = i * pointer_size
        method_ptr_expr = f'(void *)((void **)0x{method_list_ptr:x})[{i}]'
        method_ptr_result = frame.EvaluateExpression(method_ptr_expr)

        if not method_ptr_result.IsValid() or method_ptr_result.GetError().Fail():
            continue

        method_ptr = method_ptr_result.GetValueAsUnsigned()

        if method_ptr == 0:
            continue

        # Get selector name using method_getName
        sel_name_expr = f'(const char *)sel_getName((SEL)method_getName((void *)0x{method_ptr:x}))'
        sel_name_result = frame.EvaluateExpression(sel_name_expr)

        if sel_name_result.IsValid() and not sel_name_result.GetError().Fail():
            sel_name = sel_name_result.GetSummary()
            if sel_name:
                sel_name = unquote_string(sel_name)

                # Apply pattern filter if provided
                if matches_pattern(sel_name, pattern):
                    selectors.append(sel_name)

    # Clean up allocated memory
    if method_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')

    return selectors

def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Find Objective-C selectors (methods) for a class. '
        'Usage: osel ClassName [pattern]" '
        '-f objc_sel.find_objc_selectors osel'
    )
    print(f"[lldb-objc v{__version__}] Objective-C selector finder command 'osel' has been installed.")
    print("Usage: osel ClassName [pattern]")
