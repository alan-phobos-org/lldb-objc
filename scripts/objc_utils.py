#!/usr/bin/env python3
"""
LLDB-dependent utilities for Objective-C automation scripts.

This module provides LLDB-dependent functionality:
- Method resolution (class, selector, IMP lookup via LLDB)
- Runtime introspection using frame.EvaluateExpression()
- Architecture-specific register access

For pure Python utilities (parsing, formatting), see objc_core.py
"""

from __future__ import annotations

import lldb
import os
import sys
from typing import Optional, Tuple, List

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Import pure Python utilities from objc_core
from objc_core import extract_inherited_class

# -----------------------------------------------------------------------------
# Expression Evaluation Optimization
# -----------------------------------------------------------------------------
# These utilities provide optimized expression evaluation by:
# 1. Setting expression options that reduce overhead (skip breakpoints, single thread)
# 2. Providing a consistent interface for expression evaluation across the codebase
# 3. Caching expression options to avoid repeated object creation

# Global cached expression options (created once per process)
_cached_expr_options: Optional[lldb.SBExpressionOptions] = None


def get_expression_options(
    timeout_seconds: float = 30.0,
    ignore_breakpoints: bool = True,
    try_all_threads: bool = False,
    unwind_on_error: bool = True,
) -> lldb.SBExpressionOptions:
    """
    Get optimized expression options for LLDB expression evaluation.

    These options significantly reduce overhead for expression evaluation by:
    - Ignoring breakpoints during evaluation (avoids unnecessary checks)
    - Using only the current thread (avoids thread switching overhead)
    - Setting appropriate timeouts

    Args:
        timeout_seconds: Maximum time for expression evaluation (default: 30s)
        ignore_breakpoints: Skip breakpoint checks during evaluation (default: True)
        try_all_threads: Try other threads if current fails (default: False)
        unwind_on_error: Unwind stack on error (default: True)

    Returns:
        Configured SBExpressionOptions object
    """
    global _cached_expr_options

    # Use cached options for default parameters (most common case)
    if timeout_seconds == 30.0 and ignore_breakpoints and not try_all_threads and unwind_on_error:
        if _cached_expr_options is None:
            _cached_expr_options = lldb.SBExpressionOptions()
            _cached_expr_options.SetIgnoreBreakpoints(True)
            _cached_expr_options.SetTryAllThreads(False)
            _cached_expr_options.SetUnwindOnError(True)
            _cached_expr_options.SetTimeoutInMicroSeconds(int(30.0 * 1_000_000))
            _cached_expr_options.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
        return _cached_expr_options

    # Create new options for non-default parameters
    options = lldb.SBExpressionOptions()
    options.SetIgnoreBreakpoints(ignore_breakpoints)
    options.SetTryAllThreads(try_all_threads)
    options.SetUnwindOnError(unwind_on_error)
    options.SetTimeoutInMicroSeconds(int(timeout_seconds * 1_000_000))
    options.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
    return options


def evaluate_expression(
    frame: lldb.SBFrame,
    expr: str,
    timeout_seconds: float = 30.0,
    options: Optional[lldb.SBExpressionOptions] = None,
) -> lldb.SBValue:
    """
    Evaluate an expression with optimized settings.

    This is a convenience wrapper around frame.EvaluateExpression that
    automatically applies performance-optimized expression options.

    Args:
        frame: The LLDB SBFrame for expression evaluation
        expr: The expression string to evaluate
        timeout_seconds: Maximum time for evaluation (default: 30s, ignored if options provided)
        options: Optional custom SBExpressionOptions (uses optimized defaults if None)

    Returns:
        SBValue result from the expression evaluation

    Example:
        result = evaluate_expression(frame, '(Class)NSClassFromString(@"NSObject")')
        if result.IsValid() and not result.GetError().Fail():
            ptr = result.GetValueAsUnsigned()
    """
    if options is None:
        options = get_expression_options(timeout_seconds=timeout_seconds)
    return frame.EvaluateExpression(expr, options)


def evaluate_expression_value(
    frame: lldb.SBFrame,
    expr: str,
    default: int = 0,
) -> int:
    """
    Evaluate an expression and return its unsigned integer value.

    Convenience function for the common pattern of evaluating an expression
    and extracting an unsigned integer result.

    Args:
        frame: The LLDB SBFrame for expression evaluation
        expr: The expression string to evaluate
        default: Value to return on error (default: 0)

    Returns:
        Unsigned integer value of the result, or default on error
    """
    result = evaluate_expression(frame, expr)
    if result.IsValid() and not result.GetError().Fail():
        return result.GetValueAsUnsigned()
    return default


def evaluate_expression_string(
    frame: lldb.SBFrame,
    expr: str,
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Evaluate an expression and return its string summary.

    Convenience function for the common pattern of evaluating an expression
    and extracting a string result (e.g., from const char* expressions).

    Args:
        frame: The LLDB SBFrame for expression evaluation
        expr: The expression string to evaluate
        default: Value to return on error (default: None)

    Returns:
        String summary of the result, or default on error
    """
    result = evaluate_expression(frame, expr)
    if result.IsValid() and not result.GetError().Fail():
        return result.GetSummary()
    return default


def resolve_method_address(
    frame: lldb.SBFrame,
    class_name: str,
    selector: str,
    is_instance_method: bool,
    verbose: bool = False,
) -> Tuple[lldb.SBAddress, int, int, Optional[str], int]:
    """
    Resolve an Objective-C method to its implementation address.

    Uses runtime introspection:
    1. NSClassFromString() to get Class pointer
    2. NSSelectorFromString() to get SEL pointer
    3. object_getClass() for metaclass (class methods)
    4. class_getMethodImplementation() to get IMP address
    5. ResolveLoadAddress() to get SBAddress for symbol lookup

    Args:
        frame: The LLDB SBFrame to use for expression evaluation
        class_name: Name of the Objective-C class
        selector: The selector string (e.g., "initWithFrame:")
        is_instance_method: True for instance methods (-), False for class methods (+)
        verbose: If True, print resolution details

    Returns:
        Tuple of (resolved_address, class_ptr, sel_ptr, error_message, raw_imp_addr)
        - resolved_address: lldb.SBAddress (for symbol lookup; may be invalid on error)
        - class_ptr, sel_ptr: int pointers for reference
        - error_message: None on success, error string on failure
        - raw_imp_addr: The raw IMP address from class_getMethodImplementation (use this for breakpoints)
        On error, resolved_address is invalid and error_message describes the issue
    """
    # Step 1: Get the class using NSClassFromString
    target = frame.GetThread().GetProcess().GetTarget()
    invalid_addr = lldb.SBAddress()

    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = evaluate_expression(frame, class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return (
            invalid_addr,
            0,
            0,
            f"Failed to resolve class '{class_name}': {class_result.GetError()}",
            0,
        )

    class_ptr = class_result.GetValueAsUnsigned()

    if verbose:
        print(f"  Class: {class_result.GetValue()}")

    if class_ptr == 0:
        return invalid_addr, 0, 0, f"Class '{class_name}' not found", 0

    # Step 2: Get the selector using NSSelectorFromString
    sel_expr = f'(SEL)NSSelectorFromString(@"{selector}")'
    sel_result = evaluate_expression(frame, sel_expr)

    if not sel_result.IsValid() or sel_result.GetError().Fail():
        return (
            invalid_addr,
            class_ptr,
            0,
            f"Failed to resolve selector '{selector}': {sel_result.GetError()}",
            0,
        )

    sel_ptr = sel_result.GetValueAsUnsigned()

    if verbose:
        print(f"  SEL: {sel_result.GetValue()}")

    if sel_ptr == 0:
        return invalid_addr, class_ptr, 0, f"Selector '{selector}' not found", 0

    # Step 3: For class methods, get the metaclass
    lookup_class_ptr = class_ptr
    if not is_instance_method:
        metaclass_expr = f"(Class)object_getClass((id)0x{class_ptr:x})"
        metaclass_result = evaluate_expression(frame, metaclass_expr)

        if not metaclass_result.IsValid() or metaclass_result.GetError().Fail():
            return (
                invalid_addr,
                class_ptr,
                sel_ptr,
                f"Failed to get metaclass: {metaclass_result.GetError()}",
                0,
            )

        lookup_class_ptr = metaclass_result.GetValueAsUnsigned()

    # Step 4: Get the method implementation using class_getMethodImplementation
    imp_expr = f"(void *)class_getMethodImplementation((Class)0x{lookup_class_ptr:x}, (SEL)0x{sel_ptr:x})"
    imp_result = evaluate_expression(frame, imp_expr)

    if not imp_result.IsValid() or imp_result.GetError().Fail():
        return (
            invalid_addr,
            class_ptr,
            sel_ptr,
            f"Failed to get method implementation: {imp_result.GetError()}",
            0,
        )

    imp_addr = imp_result.GetValueAsUnsigned()

    if imp_addr == 0:
        if verbose:
            print(f"  IMP: {imp_result.GetValue()}")
        return invalid_addr, class_ptr, sel_ptr, "Method implementation not found", 0

    # Step 5: Resolve load address to SBAddress and check for forwarding or inheritance
    addr = target.ResolveLoadAddress(imp_addr)
    inherited_from = None

    if not addr.IsValid():
        # SBAddress resolution failed, but we still have the raw IMP - return it
        # The caller can still use the raw address for breakpoints
        return (
            invalid_addr,
            class_ptr,
            sel_ptr,
            None,  # Not an error - we have the raw address
            imp_addr,
        )

    symbol = addr.GetSymbol()
    if symbol.IsValid():
        symbol_name = symbol.GetName()
        if symbol_name:
            # Check for forwarding stub
            if "msgForward" in symbol_name:
                if verbose:
                    print(f"  IMP: {imp_result.GetValue()}")
                method_type = "instance" if is_instance_method else "class"
                return (
                    invalid_addr,
                    class_ptr,
                    sel_ptr,
                    (
                        f"Method not implemented: {method_type} method '{selector}' "
                        f"on class '{class_name}' resolves to forwarding stub ({symbol_name})"
                    ),
                    imp_addr,
                )

            # Check if method is inherited from a superclass
            # Symbol format: +[ClassName selector] or -[ClassName selector]
            inherited_from = extract_inherited_class(symbol_name, class_name, selector, is_instance_method)

    if verbose:
        if inherited_from:
            prefix = "-" if is_instance_method else "+"
            print(
                f"  IMP: {imp_result.GetValue()} \033[90m(inherited from {prefix}[{inherited_from} {selector}])\033[0m"
            )
        else:
            print(f"  IMP: {imp_result.GetValue()}")

    return addr, class_ptr, sel_ptr, None, imp_addr


def detect_method_type(frame: lldb.SBFrame, class_name: str, selector: str, verbose: bool = False) -> bool:
    """
    Auto-detect whether a method is a class method (+) or instance method (-).

    Args:
        frame: The LLDB SBFrame to use for expression evaluation
        class_name: Name of the Objective-C class
        selector: The selector string
        verbose: If True, print detection details

    Returns:
        True for instance method, False for class method.

    Logic:
    - Check if the class has this method as a class method first
    - If not found as class method, check instance method
    - Default to instance method if we can't determine
    """
    # Check for class method first using class_getClassMethod
    # This is more reliable than class_respondsToSelector for our purposes
    check_expr = f'''(void *)({{
        Class cls = (Class)NSClassFromString(@"{class_name}");
        if (!cls) (void *)0;
        SEL sel = (SEL)NSSelectorFromString(@"{selector}");
        (void *)class_getClassMethod(cls, sel);
    }})'''

    class_result = evaluate_expression(frame, check_expr)
    if class_result.IsValid() and not class_result.GetError().Fail():
        has_class_method = class_result.GetValueAsUnsigned() != 0
        if has_class_method:
            if verbose:
                print(f"Auto-detect: Class method +[{class_name} {selector}]")
            return False  # is_instance_method = False

    # Check for instance method using class_getInstanceMethod
    check_expr = f'''(void *)({{
        Class cls = (Class)NSClassFromString(@"{class_name}");
        if (!cls) (void *)0;
        SEL sel = (SEL)NSSelectorFromString(@"{selector}");
        (void *)class_getInstanceMethod(cls, sel);
    }})'''

    instance_result = evaluate_expression(frame, check_expr)
    if instance_result.IsValid() and not instance_result.GetError().Fail():
        has_instance_method = instance_result.GetValueAsUnsigned() != 0
        if has_instance_method:
            if verbose:
                print(f"Auto-detect: Instance method -[{class_name} {selector}]")
            return True  # is_instance_method = True

    # Default to instance method if we can't determine
    if verbose:
        print(f"Auto-detect: Defaulting to instance method -[{class_name} {selector}]")
    return True


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

    if "arm64" in triple or "aarch64" in triple:
        # ARM64: x0=self, x1=_cmd, x2-x7=args
        return ("x0", "x1", ["x2", "x3", "x4", "x5", "x6", "x7"])
    else:
        # x86_64: rdi=self, rsi=_cmd, rdx, rcx, r8, r9=args
        return ("rdi", "rsi", ["rdx", "rcx", "r8", "r9"])
