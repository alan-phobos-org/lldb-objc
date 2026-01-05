#!/usr/bin/env python3
"""
LLDB script for inspecting Objective-C object instances.
Usage: oinstance <address|$var|expression>   # Inspect specific object
       oinstance 0x123456789abc              # Inspect by hex address
       oinstance $0                          # Inspect LLDB variable
       oinstance (id)[NSDate date]           # Inspect by expression

This command provides detailed inspection of an object including:
- Class name and description
- Class hierarchy
- Instance variables with values and types
"""

from __future__ import annotations

import lldb
import os
import sys
import struct
from typing import Any, Dict, List, Tuple

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Import helper functions from objc_cls
try:
    from objc_cls import get_class_hierarchy, get_class_ivars, decode_type_encoding
except ImportError:
    # Fallback implementations if objc_cls is not available
    def get_class_hierarchy(frame: lldb.SBFrame, class_name: str) -> List[str]:
        return [class_name]

    def get_class_ivars(frame: lldb.SBFrame, class_name: str) -> List[Tuple[str, str, int]]:
        return []

    def decode_type_encoding(type_enc: str) -> str:
        return type_enc


def read_ivar_value(
    process: lldb.SBProcess,
    frame: lldb.SBFrame,
    addr: int,
    type_enc: str
) -> Tuple[int, str]:
    """
    Read value at address and generate description based on type encoding.

    Args:
        process: LLDB process for memory reads
        frame: LLDB frame for expression evaluation
        addr: Memory address to read from
        type_enc: Objective-C type encoding

    Returns:
        (value_as_int, description_string) tuple
    """
    error = lldb.SBError()
    pointer_size = 8  # Assume 64-bit for modern systems

    # Read raw bytes
    raw_bytes = process.ReadMemory(addr, pointer_size, error)
    if not error.Success():
        return 0, "?"

    # Parse based on type encoding
    if type_enc.startswith('@'):
        # Object pointer
        obj_ptr = struct.unpack('Q', raw_bytes)[0]
        if obj_ptr == 0:
            return 0, "(nil)"

        # Get object description
        desc_expr = f'(const char *)[[(id)0x{obj_ptr:x} description] UTF8String]'
        desc_result = frame.EvaluateExpression(desc_expr)

        if desc_result.IsValid():
            desc_ptr = desc_result.GetValueAsUnsigned()
            if desc_ptr != 0:
                desc = process.ReadCStringFromMemory(desc_ptr, 60, error)
                if error.Success() and desc:
                    # Truncate long descriptions
                    if len(desc) > 40:
                        desc = desc[:37] + "..."
                    return obj_ptr, desc

        # Fallback: try to get class name
        class_expr = f'(const char *)class_getName(object_getClass((id)0x{obj_ptr:x}))'
        class_result = frame.EvaluateExpression(class_expr)
        if class_result.IsValid():
            class_name_ptr = class_result.GetValueAsUnsigned()
            if class_name_ptr != 0:
                class_name = process.ReadCStringFromMemory(class_name_ptr, 100, error)
                if error.Success() and class_name:
                    return obj_ptr, f"({class_name} instance)"

        return obj_ptr, "(object)"

    elif type_enc == '#':
        # Class object
        class_ptr = struct.unpack('Q', raw_bytes)[0]
        if class_ptr == 0:
            return 0, "(nil)"

        class_expr = f'(const char *)class_getName((Class)0x{class_ptr:x})'
        class_result = frame.EvaluateExpression(class_expr)
        if class_result.IsValid():
            name_ptr = class_result.GetValueAsUnsigned()
            if name_ptr != 0:
                class_name = process.ReadCStringFromMemory(name_ptr, 100, error)
                if error.Success() and class_name:
                    return class_ptr, f"Class ({class_name})"
        return class_ptr, "Class"

    elif type_enc == ':':
        # SEL
        sel_ptr = struct.unpack('Q', raw_bytes)[0]
        if sel_ptr == 0:
            return 0, "(NULL)"

        sel_expr = f'(const char *)sel_getName((SEL)0x{sel_ptr:x})'
        sel_result = frame.EvaluateExpression(sel_expr)
        if sel_result.IsValid():
            name_ptr = sel_result.GetValueAsUnsigned()
            if name_ptr != 0:
                sel_name = process.ReadCStringFromMemory(name_ptr, 100, error)
                if error.Success() and sel_name:
                    return sel_ptr, f"@selector({sel_name})"
        return sel_ptr, "SEL"

    elif type_enc in ['d', 'f']:
        # Double/Float
        if type_enc == 'd':
            value = struct.unpack('d', raw_bytes)[0]
            return struct.unpack('Q', raw_bytes)[0], f"{value} (double)"
        else:
            value = struct.unpack('f', raw_bytes[:4])[0]
            return struct.unpack('I', raw_bytes[:4])[0], f"{value} (float)"

    elif type_enc in ['q', 'l', 'i', 's', 'c']:
        # Signed integers
        type_map = {
            'q': ('q', 'long long'),
            'l': ('q', 'long'),
            'i': ('i', 'int'),
            's': ('h', 'short'),
            'c': ('b', 'char')
        }
        fmt, type_name = type_map[type_enc]
        value = struct.unpack(fmt, raw_bytes[:struct.calcsize(fmt)])[0]
        return value & 0xFFFFFFFFFFFFFFFF, f"{value} ({type_name})"

    elif type_enc in ['Q', 'L', 'I', 'S', 'C']:
        # Unsigned integers
        type_map = {
            'Q': ('Q', 'unsigned long long'),
            'L': ('Q', 'unsigned long'),
            'I': ('I', 'unsigned int'),
            'S': ('H', 'unsigned short'),
            'C': ('B', 'unsigned char')
        }
        fmt, type_name = type_map[type_enc]
        value = struct.unpack(fmt, raw_bytes[:struct.calcsize(fmt)])[0]
        return value, f"{value} ({type_name})"

    elif type_enc == 'B':
        # BOOL
        value = struct.unpack('B', raw_bytes[:1])[0]
        bool_str = "YES" if value else "NO"
        return value, f"{bool_str} (BOOL)"

    elif type_enc == '*':
        # char *
        str_ptr = struct.unpack('Q', raw_bytes)[0]
        if str_ptr == 0:
            return 0, "(NULL)"

        c_str = process.ReadCStringFromMemory(str_ptr, 60, error)
        if error.Success() and c_str:
            if len(c_str) > 40:
                c_str = c_str[:37] + "..."
            return str_ptr, f'"{c_str}"'
        return str_ptr, "(char *)"

    elif type_enc.startswith('^'):
        # Pointer type
        ptr_value = struct.unpack('Q', raw_bytes)[0]
        if ptr_value == 0:
            return 0, "(NULL)"
        return ptr_value, "(ptr)"

    else:
        # Unknown/struct/union - just show hex
        value = struct.unpack('Q', raw_bytes)[0]
        return value, ""


def get_ivar_values(frame: lldb.SBFrame, obj_addr: int, class_name: str) -> List[Tuple]:
    """
    Get ivar values for a specific object instance.

    Args:
        frame: LLDB frame for expression evaluation
        obj_addr: Address of the object instance
        class_name: Name of the class

    Returns:
        List of (name, type_enc, offset, value_addr, value_desc) tuples
    """
    ivars = get_class_ivars(frame, class_name)
    process = frame.GetThread().GetProcess()
    result = []

    for ivar_name, ivar_type_enc, ivar_offset in ivars:
        if ivar_offset is None:
            continue

        # Calculate actual address in memory
        ivar_addr = obj_addr + ivar_offset

        # Read value at that address
        value_addr, value_desc = read_ivar_value(
            process, frame, ivar_addr, ivar_type_enc
        )

        result.append((
            ivar_name,
            ivar_type_enc,
            ivar_offset,
            value_addr,
            value_desc
        ))

    return result


def format_object_inspection(
    obj_addr: int,
    class_name: str,
    description: str,
    hierarchy: List[str],
    ivar_values: List[Tuple]
) -> str:
    """Format the complete inspection output."""

    lines = []

    # Header
    lines.append(f"{class_name} (0x{obj_addr:016x})")

    # Description (truncated to 80 chars, one line)
    if description:
        desc = description.replace('\n', ' ')
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(f"  {desc}")

    # Class hierarchy (if not just NSObject)
    if hierarchy and len(hierarchy) > 1:
        lines.append("")
        lines.append("  Class Hierarchy:")
        hierarchy_str = " → ".join(hierarchy[1:])
        lines.append(f"    {hierarchy[0]} \033[90m→ {hierarchy_str}\033[0m")

    # Instance variables with values
    if ivar_values:
        lines.append("")
        lines.append(f"  Instance Variables ({len(ivar_values)}):")

        for name, type_enc, offset, value_addr, value_desc in ivar_values:
            # Decode type for display
            type_str = decode_type_encoding(type_enc)

            # Format line
            # offset (dim) + name (normal) + address (hex) + description + (type in dim)
            offset_str = f"\033[90m0x{offset:03x}\033[0m"
            addr_str = f"0x{value_addr:016x}"

            if value_desc:
                # Value description already includes type info
                lines.append(f"    {offset_str}  {name:20s}  {addr_str}  {value_desc}")
            else:
                type_part = f"\033[90m{type_str}\033[0m"
                lines.append(f"    {offset_str}  {name:20s}  {addr_str}  {type_part}")
    else:
        lines.append("")
        lines.append("  Instance Variables: none")

    return '\n'.join(lines)


def inspect_object(
    frame: lldb.SBFrame,
    obj_input: str
) -> str:
    """
    Inspect a specific object instance.

    Args:
        frame: LLDB frame for expression evaluation
        obj_input: Address (0x...), variable ($0), or expression (self, etc.)

    Returns:
        Formatted inspection output or error message
    """
    process = frame.GetThread().GetProcess()

    # Step 1: Resolve address from input
    obj_addr = 0

    # Try parsing as hex address first
    if obj_input.startswith("0x") or obj_input.startswith("0X"):
        try:
            obj_addr = int(obj_input, 16)
        except ValueError:
            return f"Error: Invalid hex address '{obj_input}'"
    else:
        # Evaluate as expression to get the object pointer value
        var_expr = f'{obj_input}'
        var_result = frame.EvaluateExpression(var_expr)

        if not var_result.IsValid() or var_result.GetError().Fail():
            return f"Error: Could not evaluate expression '{obj_input}': {var_result.GetError()}"

        # Now get the address from the evaluated value
        obj_addr = var_result.GetValueAsUnsigned()

    # Validate address
    if obj_addr == 0:
        return "Error: Invalid object address (nil)"

    # Step 2: Validate it's an Objective-C object and get class name
    class_expr = f'(const char *)class_getName((Class)[(id)0x{obj_addr:x} class])'
    class_result = frame.EvaluateExpression(class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return f"Error: Not a valid Objective-C object at 0x{obj_addr:x}: {class_result.GetError()}"

    class_name_ptr = class_result.GetValueAsUnsigned()
    if class_name_ptr == 0:
        return f"Error: Not a valid Objective-C object at 0x{obj_addr:x}"

    error = lldb.SBError()
    class_name = process.ReadCStringFromMemory(class_name_ptr, 256, error)
    if not error.Success() or not class_name:
        return f"Error: Could not read class name for object at 0x{obj_addr:x}"

    # Step 3: Get object description
    desc_expr = f'(const char *)[[(id)0x{obj_addr:x} description] UTF8String]'
    desc_result = frame.EvaluateExpression(desc_expr)

    description = ""
    if desc_result.IsValid() and not desc_result.GetError().Fail():
        desc_ptr = desc_result.GetValueAsUnsigned()
        if desc_ptr != 0:
            desc_bytes = process.ReadCStringFromMemory(desc_ptr, 256, error)
            if error.Success() and desc_bytes:
                description = desc_bytes

    # Step 4: Get class hierarchy
    hierarchy = get_class_hierarchy(frame, class_name)

    # Step 5: Get ivar values
    ivar_values = get_ivar_values(frame, obj_addr, class_name)

    # Step 6: Format and return output
    return format_object_inspection(obj_addr, class_name, description, hierarchy, ivar_values)


def inspect_instance_command(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    LLDB command to inspect an Objective-C object instance.

    Usage: oinstance <address|$var|expression>
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse arguments
    obj_input = command.strip()

    if not obj_input:
        result.SetError("Usage: oinstance <address|$var|expression>")
        return

    # Get current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Inspect the object
    output = inspect_object(frame, obj_input)
    print(output)
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the oinstance command when this module is loaded in LLDB."""
    debugger.HandleCommand(
        'command script add -f objc_instance.inspect_instance_command oinstance'
    )
    print(f"[lldb-objc v{__version__}] Object inspector 'oinstance' has been installed.")
