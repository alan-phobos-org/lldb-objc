#!/usr/bin/env python3
"""
LLDB script for calling Objective-C methods from the command line.
Usage: ocall +[ClassName selector:]           # Class method
       ocall +[ClassName selector:arg1]       # Class method with argument
       ocall -[$variable selector:]           # Instance method on variable
       ocall -[$register selector:]           # Instance method on register (e.g., $x0)
       ocall -[0x123456 selector:]            # Instance method on address
       ocall --verbose +[ClassName selector:] # Shows resolution chain
"""

from __future__ import annotations

import lldb
import os
import sys
from typing import Any, Dict

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"


def call_objc_method(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Call an Objective-C method and display the result.
    Supports both class methods and instance methods.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse command for verbose flag
    command = command.strip()
    verbose = False

    if command.startswith('--verbose ') or command.startswith('-v '):
        verbose = True
        command = command.split(None, 1)[1] if ' ' in command else ''
        command = command.strip()

    # Validate basic syntax
    if not (command.startswith('-[') or command.startswith('+[')):
        result.SetError("Usage: ocall -[receiver selector:] or ocall +[ClassName selector:]\n"
                       "       ocall --verbose +[ClassName selector:]")
        return

    is_class_method = command.startswith('+[')

    # Find the matching closing bracket
    bracket_count = 0
    end_idx = -1
    for i, c in enumerate(command):
        if c == '[':
            bracket_count += 1
        elif c == ']':
            bracket_count -= 1
            if bracket_count == 0:
                end_idx = i
                break

    if end_idx == -1:
        result.SetError("Invalid syntax: missing closing bracket ']'")
        return

    # Extract the content between brackets
    method_str = command[2:end_idx]

    # Split into receiver and selector+args
    # The receiver is the first token, rest is selector with args
    parts = method_str.split(None, 1)

    if len(parts) < 2:
        result.SetError("Invalid format. Expected: +[ClassName selector:] or -[receiver selector:]")
        return

    receiver = parts[0]
    selector_with_args = parts[1]

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    if is_class_method:
        # Class method: receiver is class name
        class_name = receiver

        if verbose:
            print(f"Resolving class method: +[{class_name} {selector_with_args}]")

        # Resolve the class using NSClassFromString
        class_expr = f'(Class)NSClassFromString(@"{class_name}")'
        class_result = frame.EvaluateExpression(class_expr)

        if not class_result.IsValid() or class_result.GetError().Fail():
            result.SetError(f"Failed to resolve class '{class_name}': {class_result.GetError()}")
            return

        class_ptr = class_result.GetValueAsUnsigned()

        if class_ptr == 0:
            result.SetError(f"Class '{class_name}' not found")
            return

        if verbose:
            print(f"  Class: {class_result.GetValue()}")
            # Get selector for verbose output
            sel_name = extract_selector_name(selector_with_args)
            sel_expr = f'(SEL)NSSelectorFromString(@"{sel_name}")'
            sel_result = frame.EvaluateExpression(sel_expr)
            if sel_result.IsValid() and not sel_result.GetError().Fail():
                print(f"  SEL: {sel_result.GetValue()}")

        # Build and execute the expression
        # For class methods, cast to (id) to avoid type ambiguity
        # The key is that we need to make LLDB treat this as a valid method call
        call_expr = f'(id)[(Class)NSClassFromString(@"{class_name}") {selector_with_args}]'

    else:
        # Instance method: receiver can be $variable, $register, or hex address
        if verbose:
            print(f"Resolving instance method: -[{receiver} {selector_with_args}]")

        # Determine receiver type and build expression
        if receiver.startswith('$'):
            # Variable or register reference
            # Check if it's a valid variable/register in the frame
            var_name = receiver  # Keep the $ prefix
            # Cast both the receiver and the entire message send to avoid type ambiguity
            call_expr = f'(id)[(id){var_name} {selector_with_args}]'

            if verbose:
                # Try to get the value of the variable/register
                var_result = frame.EvaluateExpression(f'(void*){var_name}')
                if var_result.IsValid() and not var_result.GetError().Fail():
                    print(f"  Receiver ({var_name}): {var_result.GetValue()}")
                else:
                    print(f"  Receiver: {var_name}")

        elif receiver.startswith('0x') or receiver.isdigit():
            # Hex address or numeric address
            # Cast both the receiver and the entire message send to avoid type ambiguity
            call_expr = f'(id)[(id){receiver} {selector_with_args}]'

            if verbose:
                print(f"  Receiver (address): {receiver}")

        else:
            result.SetError(f"Invalid receiver '{receiver}'. For instance methods, use $variable, $register, or hex address.")
            return

        if verbose:
            # Get selector for verbose output
            sel_name = extract_selector_name(selector_with_args)
            sel_expr = f'(SEL)NSSelectorFromString(@"{sel_name}")'
            sel_result = frame.EvaluateExpression(sel_expr)
            if sel_result.IsValid() and not sel_result.GetError().Fail():
                print(f"  SEL: {sel_result.GetValue()}")

    # Execute the method call
    if verbose:
        print(f"\nExecuting: {call_expr}")
        print()

    call_result = frame.EvaluateExpression(call_expr)

    if not call_result.IsValid() or call_result.GetError().Fail():
        error_msg = str(call_result.GetError()) if call_result.GetError().Fail() else "Unknown error"
        result.SetError(f"Method call failed: {error_msg}")
        return

    # Display the result
    display_result(call_result)

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def extract_selector_name(selector_with_args: str) -> str:
    """
    Extract just the selector name from a selector with arguments.
    E.g., 'stringWithString:@"hello"' -> 'stringWithString:'
          'initWithFrame:rect style:3' -> 'initWithFrame:style:'
          'initWithString:@"text)withParen"' -> 'initWithString:'

    Handles:
    - Objective-C string literals (@"...")
    - Escaped quotes within strings
    - Nested parentheses
    - Numeric and hex literals
    - Variable references ($var)
    """
    result = []
    i = 0
    n = len(selector_with_args)

    while i < n:
        c = selector_with_args[i]

        # Skip Objective-C string literals @"..."
        if c == '@' and i + 1 < n and selector_with_args[i + 1] == '"':
            i += 2  # Skip @"
            while i < n:
                if selector_with_args[i] == '\\' and i + 1 < n:
                    i += 2  # Skip escaped character
                elif selector_with_args[i] == '"':
                    i += 1  # Skip closing quote
                    break
                else:
                    i += 1
            continue

        # Skip C string literals "..."
        if c == '"':
            i += 1
            while i < n:
                if selector_with_args[i] == '\\' and i + 1 < n:
                    i += 2
                elif selector_with_args[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Skip parenthesized expressions (handles nesting)
        if c == '(':
            depth = 1
            i += 1
            while i < n and depth > 0:
                if selector_with_args[i] == '(':
                    depth += 1
                elif selector_with_args[i] == ')':
                    depth -= 1
                i += 1
            continue

        # Skip bracket expressions (e.g., array subscripts)
        if c == '[':
            depth = 1
            i += 1
            while i < n and depth > 0:
                if selector_with_args[i] == '[':
                    depth += 1
                elif selector_with_args[i] == ']':
                    depth -= 1
                i += 1
            continue

        # Skip variable references ($var)
        if c == '$':
            i += 1
            while i < n and (selector_with_args[i].isalnum() or selector_with_args[i] == '_'):
                i += 1
            continue

        # Skip hex literals (0x...)
        if c == '0' and i + 1 < n and selector_with_args[i + 1] in 'xX':
            i += 2
            while i < n and selector_with_args[i] in '0123456789abcdefABCDEF':
                i += 1
            continue

        # Skip numeric literals
        if c.isdigit():
            while i < n and (selector_with_args[i].isdigit() or selector_with_args[i] == '.'):
                i += 1
            continue

        # Collect identifier parts (selector components)
        if c.isalpha() or c == '_':
            word = ''
            while i < n and (selector_with_args[i].isalnum() or selector_with_args[i] == '_'):
                word += selector_with_args[i]
                i += 1
            # Check if followed by colon (selector part)
            if i < n and selector_with_args[i] == ':':
                result.append(word + ':')
                i += 1
            elif not result:
                # First word might be a no-arg selector
                result.append(word)
            continue

        # Skip whitespace and other characters
        i += 1

    return ''.join(result)


def display_result(sbvalue: lldb.SBValue) -> None:
    """
    Display an SBValue result in a readable format.
    """
    # Get the type
    type_name = sbvalue.GetTypeName()

    # Get the value representation
    value = sbvalue.GetValue()
    summary = sbvalue.GetSummary()
    description = sbvalue.GetObjectDescription()

    # Choose the best representation
    if description:
        # Object description is usually the most informative for ObjC objects
        print(f"({type_name}) {description}")
    elif summary:
        print(f"({type_name}) {summary}")
    elif value:
        print(f"({type_name}) {value}")
    else:
        # Try to get the value as unsigned for pointers
        unsigned_val = sbvalue.GetValueAsUnsigned()
        if unsigned_val != 0:
            print(f"({type_name}) 0x{unsigned_val:x}")
        else:
            print(f"({type_name}) <no value>")


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Call Objective-C methods. '
        'Usage: ocall +[ClassName selector:] or ocall -[$variable selector:] [--verbose]" '
        '-f objc_call.call_objc_method ocall'
    )
    print(f"[lldb-objc v{__version__}] Objective-C method caller command 'ocall' has been installed.")
    print("Usage: ocall +[ClassName selector:]")
    print("       ocall -[$variable selector:]")
    print("       ocall --verbose +[ClassName selector:]")
