#!/usr/bin/env python3
"""
LLDB script for finding selectors in Objective-C classes.
Usage: ofind ClassName [pattern]
       ofind ClassName           # List all selectors
       ofind ClassName service   # Find selectors containing 'service'
       ofind ClassName *ternal   # Find selectors ending with 'ternal' (wildcard)
       ofind ClassName _init*    # Find selectors starting with '_init' (wildcard)
       ofind ClassName *set*     # Find selectors containing 'set' anywhere (wildcard)

Pattern matching:
  - Simple text: substring match (case-insensitive)
  - With *: matches any sequence of characters
  - With ?: matches any single character
"""

import lldb
import re
import os
import sys

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

def find_objc_selectors(debugger, command, result, internal_dict):
    """
    Find selectors in an Objective-C class.
    Lists both instance and class methods, optionally filtered by pattern.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the input: ClassName [pattern]
    args = command.strip().split(None, 1)

    if len(args) < 1:
        result.SetError("Usage: ofind ClassName [pattern]")
        return

    class_name = args[0]
    pattern = args[1] if len(args) > 1 else None

    print(f"Searching for selectors in class: {class_name}")
    if pattern:
        print(f"Filter pattern: {pattern}")

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Get the class using NSClassFromString
    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        result.SetError(f"Failed to resolve class '{class_name}': {class_result.GetError()}")
        return

    class_ptr = class_result.GetValueAsUnsigned()

    if class_ptr == 0:
        result.SetError(f"Class '{class_name}' not found")
        return

    print(f"Class pointer: {class_result.GetValue()}\n")

    # Find instance methods
    instance_methods = get_methods(frame, class_ptr, is_instance=True, pattern=pattern)

    # Get metaclass for class methods
    metaclass_expr = f'(Class)object_getClass((id)0x{class_ptr:x})'
    metaclass_result = frame.EvaluateExpression(metaclass_expr)

    if metaclass_result.IsValid() and not metaclass_result.GetError().Fail():
        metaclass_ptr = metaclass_result.GetValueAsUnsigned()
        class_methods = get_methods(frame, metaclass_ptr, is_instance=False, pattern=pattern)
    else:
        class_methods = []

    # Display results
    if instance_methods:
        print(f"Instance methods ({len(instance_methods)}):")
        for sel_name in sorted(instance_methods):
            print(f"  -{sel_name}")
    else:
        print("No instance methods found")

    if class_methods:
        print(f"\nClass methods ({len(class_methods)}):")
        for sel_name in sorted(class_methods):
            print(f"  +{sel_name}")
    else:
        print("\nNo class methods found")

    total = len(instance_methods) + len(class_methods)
    print(f"\nTotal: {total} method(s)")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def matches_pattern(selector_name, pattern):
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

def get_methods(frame, class_ptr, is_instance=True, pattern=None):
    """
    Get all methods for a class using class_copyMethodList.
    Returns a list of selector names.
    """
    # Get method count
    count_expr = f'(unsigned int)0'
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
                # Remove quotes from the string
                sel_name = sel_name.strip('"')

                # Apply pattern filter if provided
                if matches_pattern(sel_name, pattern):
                    selectors.append(sel_name)

    # Clean up allocated memory
    if method_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{method_list_ptr:x})')
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')

    return selectors

def __lldb_init_module(debugger, internal_dict):
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -f objc_find.find_objc_selectors ofind'
    )
    print(f"[lldb-objc v{__version__}] Objective-C selector finder command 'ofind' has been installed.")
    print("Usage: ofind ClassName [pattern]")
