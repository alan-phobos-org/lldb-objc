#!/usr/bin/env python3
"""
Shared utilities for LLDB Objective-C automation scripts.

This module provides common functionality used by multiple commands:
- Method resolution (class, selector, IMP lookup)
- Method signature parsing (-[Class sel] or +[Class sel])
- String handling utilities
- Version import handling
"""

from __future__ import annotations

import lldb
import os
import sys
from typing import Optional, Tuple, List

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"


def unquote_string(s: Optional[str]) -> Optional[str]:
    """
    Remove exactly one pair of quotes from a string and unescape internal quotes.

    IMPORTANT: Never use strip('"') - it removes ALL consecutive quotes from both ends,
    corrupting strings like '"@\\"NSString\\""' to '@\\"NSString\\'.

    Args:
        s: A string that may be wrapped in double quotes

    Returns:
        The unquoted string with internal escaped quotes unescaped

    Examples:
        >>> unquote_string('"hello"')
        'hello'
        >>> unquote_string('"@\\"NSString\\""')
        '@"NSString"'
        >>> unquote_string('no quotes')
        'no quotes'
    """
    if s and len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('\\"', '"')
    return s


def parse_method_signature(command: str) -> Tuple[Optional[bool], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a method signature like -[ClassName selector:] or +[ClassName selector:]

    Args:
        command: The method signature string

    Returns:
        Tuple of (is_instance_method, class_name, selector, error_message)
        On error, is_instance_method/class_name/selector are None
    """
    command = command.strip()

    if not (command.startswith('-[') or command.startswith('+[')):
        return None, None, None, "Expected -[ClassName selector:] or +[ClassName selector:]"

    is_instance_method = command.startswith('-[')

    # Remove the leading -[ or +[ and trailing ]
    method_str = command[2:-1] if command.endswith(']') else command[2:]
    parts = method_str.split(None, 1)  # Split on first whitespace

    if len(parts) != 2:
        return None, None, None, "Invalid format. Expected: -[ClassName selector:]"

    class_name = parts[0]
    selector = parts[1]

    return is_instance_method, class_name, selector, None


def resolve_method_address(
    frame: lldb.SBFrame,
    class_name: str,
    selector: str,
    is_instance_method: bool,
    verbose: bool = False
) -> Tuple[int, int, int, Optional[str]]:
    """
    Resolve an Objective-C method to its implementation address.

    Uses runtime introspection:
    1. NSClassFromString() to get Class pointer
    2. NSSelectorFromString() to get SEL pointer
    3. object_getClass() for metaclass (class methods)
    4. class_getMethodImplementation() to get IMP address

    Args:
        frame: The LLDB SBFrame to use for expression evaluation
        class_name: Name of the Objective-C class
        selector: The selector string (e.g., "initWithFrame:")
        is_instance_method: True for instance methods (-), False for class methods (+)
        verbose: If True, print resolution details

    Returns:
        Tuple of (imp_address, class_ptr, sel_ptr, error_message)
        On error, addresses are 0 and error_message describes the issue
    """
    # Step 1: Get the class using NSClassFromString
    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return 0, 0, 0, f"Failed to resolve class '{class_name}': {class_result.GetError()}"

    class_ptr = class_result.GetValueAsUnsigned()

    if verbose:
        print(f"  Class: {class_result.GetValue()}")

    if class_ptr == 0:
        return 0, 0, 0, f"Class '{class_name}' not found"

    # Step 2: Get the selector using NSSelectorFromString
    sel_expr = f'(SEL)NSSelectorFromString(@"{selector}")'
    sel_result = frame.EvaluateExpression(sel_expr)

    if not sel_result.IsValid() or sel_result.GetError().Fail():
        return 0, class_ptr, 0, f"Failed to resolve selector '{selector}': {sel_result.GetError()}"

    sel_ptr = sel_result.GetValueAsUnsigned()

    if verbose:
        print(f"  SEL: {sel_result.GetValue()}")

    if sel_ptr == 0:
        return 0, class_ptr, 0, f"Selector '{selector}' not found"

    # Step 3: For class methods, get the metaclass
    lookup_class_ptr = class_ptr
    if not is_instance_method:
        metaclass_expr = f'(Class)object_getClass((id)0x{class_ptr:x})'
        metaclass_result = frame.EvaluateExpression(metaclass_expr)

        if not metaclass_result.IsValid() or metaclass_result.GetError().Fail():
            return 0, class_ptr, sel_ptr, f"Failed to get metaclass: {metaclass_result.GetError()}"

        lookup_class_ptr = metaclass_result.GetValueAsUnsigned()

    # Step 4: Get the method implementation using class_getMethodImplementation
    imp_expr = f'(void *)class_getMethodImplementation((Class)0x{lookup_class_ptr:x}, (SEL)0x{sel_ptr:x})'
    imp_result = frame.EvaluateExpression(imp_expr)

    if not imp_result.IsValid() or imp_result.GetError().Fail():
        return 0, class_ptr, sel_ptr, f"Failed to get method implementation: {imp_result.GetError()}"

    imp_addr = imp_result.GetValueAsUnsigned()

    if verbose:
        print(f"  IMP: {imp_result.GetValue()}")

    if imp_addr == 0:
        return 0, class_ptr, sel_ptr, "Method implementation not found"

    return imp_addr, class_ptr, sel_ptr, None


def format_method_name(class_name: str, selector: str, is_instance_method: bool) -> str:
    """
    Format a method name in Objective-C syntax.

    Args:
        class_name: The class name
        selector: The selector string
        is_instance_method: True for instance methods, False for class methods

    Returns:
        Formatted string like "-[NSString length]" or "+[NSDate date]"
    """
    prefix = '-' if is_instance_method else '+'
    return f"{prefix}[{class_name} {selector}]"


def get_arch_registers(frame: lldb.SBFrame) -> Tuple[str, str, List[str]]:
    """
    Get the appropriate register names for the current architecture.

    For Objective-C method calls:
    - ARM64: x0=self, x1=_cmd, x2-x7=args
    - x86_64: rdi=self, rsi=_cmd, rdx, rcx, r8, r9=args

    Args:
        frame: The LLDB SBFrame

    Returns:
        Tuple of (self_reg, cmd_reg, arg_regs) where arg_regs is a list of
        additional argument register names.
    """
    target = frame.GetThread().GetProcess().GetTarget()
    triple = target.GetTriple()

    if 'arm64' in triple or 'aarch64' in triple:
        # ARM64: x0=self, x1=_cmd, x2-x7=args
        return ('x0', 'x1', ['x2', 'x3', 'x4', 'x5', 'x6', 'x7'])
    else:
        # x86_64: rdi=self, rsi=_cmd, rdx, rcx, r8, r9=args
        return ('rdi', 'rsi', ['rdx', 'rcx', 'r8', 'r9'])
