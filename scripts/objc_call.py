#!/usr/bin/env python3
"""
LLDB script for calling Objective-C methods from the command line.
Usage: ocall +[ClassName selector:]           # Class method
       ocall +[ClassName selector:arg1]       # Class method with argument
       ocall -[$variable selector:]           # Instance method on variable
       ocall -[$register selector:]           # Instance method on register (e.g., $x0)
       ocall -[0x123456 selector:]            # Instance method on address
       ocall [ClassName selector:]            # Auto-detect method type (+ or -)
       ocall @"string"                        # Evaluate Objective-C expression (string literal)
       ocall @42                              # Evaluate expression (NSNumber literal)
       ocall @[@"a", @"b"]                    # Evaluate expression (NSArray literal)
       ocall NSHomeDirectory()                # Evaluate expression (C function call)
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

# Guard against double initialization
_initialized = False

from objc_utils import detect_method_type as _detect_method_type_base
from objc_utils import evaluate_expression as eval_expr


def detect_method_type(frame: lldb.SBFrame, receiver: str, selector_with_args: str, verbose: bool = False) -> bool:
    """
    Auto-detect whether a method is a class method (+) or instance method (-).

    Returns True for class method, False for instance method.

    Logic:
    - If receiver looks like an instance ($var, $reg, 0x...), it's an instance method
    - Otherwise, delegates to shared detect_method_type in objc_utils
    """
    # If receiver is a variable, register, or address, it's definitely an instance method
    if receiver.startswith("$") or receiver.startswith("0x") or receiver.isdigit():
        if verbose:
            print(f"Auto-detect: Instance method (receiver is {receiver})")
        return False

    # Receiver looks like a class name - extract selector and use shared detection
    sel_name = extract_selector_name(selector_with_args)
    # _detect_method_type_base returns True for instance, False for class
    # We need to invert: return True for class method, False for instance
    is_instance = _detect_method_type_base(frame, receiver, sel_name, verbose)
    return not is_instance


def evaluate_and_display(
    frame: lldb.SBFrame,
    expression: str,
    result: lldb.SBCommandReturnObject,
    verbose: bool = False,
) -> None:
    """
    Evaluate an arbitrary Objective-C expression and display the result.

    Supports:
    - String literals: @"hello"
    - Number literals: @42, @3.14
    - Array literals: @[@"a", @"b"]
    - Dictionary literals: @{@"key": @"value"}
    - Boxed expressions: @(1+1)
    - Nested message sends: [[NSDate date] description]
    - C function calls: NSHomeDirectory()
    """
    if verbose:
        print(f"Evaluating expression: {expression}")
        print()

    # Cast to (id) to ensure proper handling of Objective-C objects
    # This allows the expression evaluator to treat the result as an object
    expr_to_eval = f"(id)({expression})"

    expr_result = eval_expr(frame, expr_to_eval)

    if not expr_result.IsValid() or expr_result.GetError().Fail():
        error_msg = str(expr_result.GetError()) if expr_result.GetError().Fail() else "Unknown error"
        result.SetError(f"Expression evaluation failed: {error_msg}")
        return

    # Display the result
    display_result(expr_result)
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def call_objc_method(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
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

    # Get the current frame for expression evaluation
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Parse command for verbose flag
    command = command.strip()
    verbose = False

    if command.startswith("--verbose ") or command.startswith("-v "):
        verbose = True
        command = command.split(None, 1)[1] if " " in command else ""
        command = command.strip()

    # Check if this is a method call syntax or an arbitrary expression
    # Method call: -[...], +[...], or [ClassName selector] (auto-detect)
    # For auto-detect, check that first word after [ is a valid identifier (not another [)
    is_method_call = command.startswith("-[") or command.startswith("+[")

    if command.startswith("[") and not command.startswith("[["):
        # Could be auto-detect method call [ClassName selector]
        # Check if it looks like a method call (first word after [ is identifier)
        inner = command[1:].lstrip()
        if inner and (inner[0].isalpha() or inner[0] == "_" or inner[0] == "$"):
            is_method_call = True

    # If not method call syntax, treat as arbitrary Objective-C expression
    if not is_method_call:
        evaluate_and_display(frame, command, result, verbose)
        return

    # Determine if we need to auto-detect method type
    auto_detect = command.startswith("[")
    is_class_method = command.startswith("+[")

    # Find the matching closing bracket
    bracket_count = 0
    end_idx = -1
    for i, c in enumerate(command):
        if c == "[":
            bracket_count += 1
        elif c == "]":
            bracket_count -= 1
            if bracket_count == 0:
                end_idx = i
                break

    if end_idx == -1:
        result.SetError("Invalid syntax: missing closing bracket ']'")
        return

    # Extract the content between brackets
    # For auto-detect mode, start at index 1 (skip '['), otherwise skip '+[' or '-['
    start_idx = 1 if auto_detect else 2
    method_str = command[start_idx:end_idx]

    # Split into receiver and selector+args
    # The receiver is the first token, rest is selector with args
    parts = method_str.split(None, 1)

    if len(parts) < 2:
        result.SetError("Invalid format. Expected: +[ClassName selector:] or -[receiver selector:]")
        return

    receiver = parts[0]
    selector_with_args = parts[1]

    # Auto-detect method type if not specified
    if auto_detect:
        is_class_method = detect_method_type(frame, receiver, selector_with_args, verbose)

    if is_class_method:
        # Class method: receiver is class name
        class_name = receiver

        if verbose:
            print(f"Resolving class method: +[{class_name} {selector_with_args}]")

        # Resolve the class using NSClassFromString
        class_expr = f'(Class)NSClassFromString(@"{class_name}")'
        class_result = eval_expr(frame, class_expr)

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
            sel_result = eval_expr(frame, sel_expr)
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
        if receiver.startswith("$"):
            # Variable or register reference
            # Check if it's a valid variable/register in the frame
            var_name = receiver  # Keep the $ prefix
            # Cast both the receiver and the entire message send to avoid type ambiguity
            call_expr = f"(id)[(id){var_name} {selector_with_args}]"

            if verbose:
                # Try to get the value of the variable/register
                var_result = eval_expr(frame, f"(void*){var_name}")
                if var_result.IsValid() and not var_result.GetError().Fail():
                    print(f"  Receiver ({var_name}): {var_result.GetValue()}")
                else:
                    print(f"  Receiver: {var_name}")

        elif receiver.startswith("0x") or receiver.isdigit():
            # Hex address or numeric address
            # Cast both the receiver and the entire message send to avoid type ambiguity
            call_expr = f"(id)[(id){receiver} {selector_with_args}]"

            if verbose:
                print(f"  Receiver (address): {receiver}")

        else:
            result.SetError(
                f"Invalid receiver '{receiver}'. For instance methods, use $variable, $register, or hex address."
            )
            return

        if verbose:
            # Get selector for verbose output
            sel_name = extract_selector_name(selector_with_args)
            sel_expr = f'(SEL)NSSelectorFromString(@"{sel_name}")'
            sel_result = eval_expr(frame, sel_expr)
            if sel_result.IsValid() and not sel_result.GetError().Fail():
                print(f"  SEL: {sel_result.GetValue()}")

    # Execute the method call
    if verbose:
        print(f"\nExecuting: {call_expr}")
        print()

    call_result = eval_expr(frame, call_expr)

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
        if c == "@" and i + 1 < n and selector_with_args[i + 1] == '"':
            i += 2  # Skip @"
            while i < n:
                if selector_with_args[i] == "\\" and i + 1 < n:
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
                if selector_with_args[i] == "\\" and i + 1 < n:
                    i += 2
                elif selector_with_args[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Skip parenthesized expressions (handles nesting)
        if c == "(":
            depth = 1
            i += 1
            while i < n and depth > 0:
                if selector_with_args[i] == "(":
                    depth += 1
                elif selector_with_args[i] == ")":
                    depth -= 1
                i += 1
            continue

        # Skip bracket expressions (e.g., array subscripts)
        if c == "[":
            depth = 1
            i += 1
            while i < n and depth > 0:
                if selector_with_args[i] == "[":
                    depth += 1
                elif selector_with_args[i] == "]":
                    depth -= 1
                i += 1
            continue

        # Skip variable references ($var)
        if c == "$":
            i += 1
            while i < n and (selector_with_args[i].isalnum() or selector_with_args[i] == "_"):
                i += 1
            continue

        # Skip hex literals (0x...)
        if c == "0" and i + 1 < n and selector_with_args[i + 1] in "xX":
            i += 2
            while i < n and selector_with_args[i] in "0123456789abcdefABCDEF":
                i += 1
            continue

        # Skip numeric literals
        if c.isdigit():
            while i < n and (selector_with_args[i].isdigit() or selector_with_args[i] == "."):
                i += 1
            continue

        # Collect identifier parts (selector components)
        if c.isalpha() or c == "_":
            word = ""
            while i < n and (selector_with_args[i].isalnum() or selector_with_args[i] == "_"):
                word += selector_with_args[i]
                i += 1
            # Check if followed by colon (selector part)
            if i < n and selector_with_args[i] == ":":
                result.append(word + ":")
                i += 1
            elif not result:
                # First word might be a no-arg selector
                result.append(word)
            continue

        # Skip whitespace and other characters
        i += 1

    return "".join(result)


def display_result(sbvalue: lldb.SBValue) -> None:
    """
    Display an SBValue result in a format matching LLDB's 'call' command output.
    Format: (Type *) $N = 0x... description
    The address is dimmed, matching the project's UI convention.
    """
    # Get the address of the object
    address = sbvalue.GetValueAsUnsigned()

    # Dim gray ANSI code for address
    DIM = "\033[90m"
    RESET = "\033[0m"

    # Get the type
    type_name = sbvalue.GetTypeName()

    # Get the variable name (e.g., $0, $1, etc.)
    var_name = sbvalue.GetName()
    if not var_name:
        var_name = "$?"

    # Get the value representation
    summary = sbvalue.GetSummary()
    description = sbvalue.GetObjectDescription()

    # Format the address part (dimmed)
    addr_str = f"{DIM}0x{address:x}{RESET}" if address != 0 else "0x0"

    # Choose the best representation for the value
    if description:
        # Object description is usually the most informative for ObjC objects
        value_str = description
    elif summary:
        value_str = summary
    else:
        value_str = None

    # Output format: (Type *) $N = 0x... description
    if value_str:
        print(f"({type_name}) {var_name} = {addr_str} {value_str}")
    else:
        print(f"({type_name}) {var_name} = {addr_str}")


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.call_objc_method"
    debugger.HandleCommand(
        'command script add -h "Call Objective-C methods or evaluate expressions. '
        'Usage: ocall +[ClassName selector:] or ocall -[$variable selector:] or ocall @\\"string\\" [--verbose]" '
        f"-f {module_path} ocall"
    )
    print(f"[lldb-objc v{__version__}] 'ocall' installed - Call Objective-C methods and evaluate expressions")
