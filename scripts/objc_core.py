#!/usr/bin/env python3
"""
Pure Python utilities for Objective-C method and class handling.

This module contains NO LLDB dependencies and can be unit tested
without any LLDB runtime. All functions are pure Python logic for:
- String parsing and formatting
- Pattern matching and filtering
- Data structure manipulation
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


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


def parse_method_signature(
    command: str,
) -> Tuple[Optional[bool], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a method signature like -[ClassName selector:], +[ClassName selector:], or [ClassName selector:]

    Args:
        command: The method signature string

    Returns:
        Tuple of (is_instance_method, class_name, selector, error_message)
        - is_instance_method: True for -, False for +, None for auto-detect (bare [)
        On error, all values are None except error_message
    """
    command = command.strip()

    # Determine method type based on prefix
    if command.startswith("-["):
        is_instance_method = True
        start_idx = 2
    elif command.startswith("+["):
        is_instance_method = False
        start_idx = 2
    elif command.startswith("["):
        is_instance_method = None  # Signal auto-detect needed
        start_idx = 1
    else:
        return (
            None,
            None,
            None,
            "Expected -[ClassName selector:], +[ClassName selector:], or [ClassName selector:]",
        )

    # Remove the leading prefix and trailing ]
    method_str = command[start_idx:-1] if command.endswith("]") else command[start_idx:]
    parts = method_str.split(None, 1)  # Split on first whitespace

    if len(parts) != 2:
        return None, None, None, "Invalid format. Expected: [ClassName selector:]"

    class_name = parts[0]
    selector = parts[1]

    return is_instance_method, class_name, selector, None


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
    prefix = "-" if is_instance_method else "+"
    return f"{prefix}[{class_name} {selector}]"


def extract_inherited_class(
    symbol_name: str, requested_class: str, selector: str, is_instance_method: bool
) -> Optional[str]:
    """
    Check if a symbol indicates the method is inherited from a superclass.

    Args:
        symbol_name: The symbol name at the IMP address (e.g., "+[NSObject hash]")
        requested_class: The class name we requested the method for
        selector: The selector we looked up
        is_instance_method: True for instance methods, False for class methods

    Returns:
        The superclass name if inherited, None if it's the requested class's own method
    """
    # Match Objective-C method symbol: +[ClassName selector] or -[ClassName selector]
    # The selector part can contain colons and arguments
    pattern = r"^[+-]\[(\w+)\s+(.+)\]$"
    match = re.match(pattern, symbol_name)

    if match:
        symbol_class = match.group(1)
        symbol_selector = match.group(2)

        # Check if it's from a different class (i.e., inherited)
        if symbol_class != requested_class:
            # Verify the selector matches (it should, but let's be safe)
            if symbol_selector == selector:
                return symbol_class

    return None


def extract_category_from_symbol(
    symbol_name: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract class name, category name, and selector from an Objective-C symbol.

    Args:
        symbol_name: Symbol like "-[NSString(CategoryName) methodName]" or "-[NSString methodName]"

    Returns:
        Tuple of (class_name, category_name, selector)
        category_name is None if the method is not from a category
    """
    # Match: +/-[ClassName(CategoryName) selector] or +/-[ClassName selector]
    pattern = r"^[+-]\[(\w+)(?:\((\w+)\))?\s+(.+)\]$"
    match = re.match(pattern, symbol_name)

    if match:
        return match.group(1), match.group(2), match.group(3)
    return None, None, None
