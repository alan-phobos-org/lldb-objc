#!/usr/bin/env python3
"""
LLDB script for setting breakpoints on Objective-C methods, including private symbols.
Usage: obrk -[ClassName selector:with:args:]
       obrk +[ClassName classMethod:]
"""

import lldb
import shlex
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

def breakpoint_on_objc_method(debugger, command, result, internal_dict):
    """
    Set a breakpoint on an Objective-C method by resolving it at runtime.
    Supports both public and private classes/methods.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse the input format: -[Class selector] or +[Class selector]
    command = command.strip()

    if not (command.startswith('-[') or command.startswith('+[')):
        result.SetError("Usage: obrk -[ClassName selector:] or obrk +[ClassName selector:]")
        return

    is_instance_method = command.startswith('-[')

    # Extract class name and selector
    # Remove the leading -[ or +[ and trailing ]
    method_str = command[2:-1] if command.endswith(']') else command[2:]
    parts = method_str.split(None, 1)  # Split on first whitespace

    if len(parts) != 2:
        result.SetError("Invalid format. Expected: -[ClassName selector:]")
        return

    class_name = parts[0]
    selector = parts[1]

    print(f"Resolving {'instance' if is_instance_method else 'class'} method: {'-' if is_instance_method else '+'}[{class_name} {selector}]")

    # Get the current frame to evaluate expressions
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Step 1: Get the class using NSClassFromString
    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        result.SetError(f"Failed to resolve class '{class_name}': {class_result.GetError()}")
        return

    class_ptr = class_result.GetValueAsUnsigned()
    print(f"  Class: {class_result.GetValue()}")

    if class_ptr == 0:
        result.SetError(f"Class '{class_name}' not found")
        return

    # Step 2: Get the selector using NSSelectorFromString
    sel_expr = f'(SEL)NSSelectorFromString(@"{selector}")'
    sel_result = frame.EvaluateExpression(sel_expr)

    if not sel_result.IsValid() or sel_result.GetError().Fail():
        result.SetError(f"Failed to resolve selector '{selector}': {sel_result.GetError()}")
        return

    sel_ptr = sel_result.GetValueAsUnsigned()
    print(f"  SEL: {sel_result.GetValue()}")

    if sel_ptr == 0:
        result.SetError(f"Selector '{selector}' not found")
        return

    # Step 3: For class methods, get the metaclass
    if not is_instance_method:
        metaclass_expr = f'(Class)object_getClass((id)0x{class_ptr:x})'
        metaclass_result = frame.EvaluateExpression(metaclass_expr)

        if not metaclass_result.IsValid() or metaclass_result.GetError().Fail():
            result.SetError(f"Failed to get metaclass: {metaclass_result.GetError()}")
            return

        class_ptr = metaclass_result.GetValueAsUnsigned()

    # Step 4: Get the method implementation using class_getMethodImplementation
    imp_expr = f'(void *)class_getMethodImplementation((Class)0x{class_ptr:x}, (SEL)0x{sel_ptr:x})'
    imp_result = frame.EvaluateExpression(imp_expr)

    if not imp_result.IsValid() or imp_result.GetError().Fail():
        result.SetError(f"Failed to get method implementation: {imp_result.GetError()}")
        return

    imp_addr = imp_result.GetValueAsUnsigned()
    print(f"  IMP: {imp_result.GetValue()}")

    if imp_addr == 0:
        result.SetError(f"Method implementation not found")
        return

    # Step 5: Set the breakpoint
    breakpoint = target.BreakpointCreateByAddress(imp_addr)

    if not breakpoint.IsValid():
        result.SetError(f"Failed to create breakpoint at 0x{imp_addr:x}")
        return

    # Set a readable name for the breakpoint
    bp_name = f"{'-' if is_instance_method else '+'}[{class_name} {selector}]"
    breakpoint.AddName(bp_name)

    print(f"\nBreakpoint #{breakpoint.GetID()} set at {bp_name}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def __lldb_init_module(debugger, internal_dict):
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -f objc_breakpoint.breakpoint_on_objc_method obrk'
    )
    print(f"[lldb-objc v{__version__}] Objective-C breakpoint command 'obrk' has been installed.")
    print("Usage: obrk -[ClassName selector:]")
    print("       obrk +[ClassName classMethod:]")
