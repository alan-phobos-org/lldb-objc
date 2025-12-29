#!/usr/bin/env python3
"""
LLDB script for finding Objective-C classes that conform to a protocol.

Usage:
    oprotos <protocol>                    # All classes conforming to protocol
    oprotos <protocol> --direct           # Only classes that directly declare conformance
    oprotos --list [pattern]              # List all protocols (optional pattern filter)
    oprotos --reload <protocol>           # Force reload class cache
    oprotos --verbose <protocol>          # Show detailed timing metrics

Examples:
    oprotos NSCoding                      # All classes conforming to NSCoding
    oprotos NSCopying --direct            # Only direct conformance (not inherited)
    oprotos *Delegate                     # Wildcard: protocols ending in "Delegate"
    oprotos --list                        # List all registered protocols
    oprotos --list NS*                    # List protocols matching pattern

Output:
    Classes are grouped by inheritance - base classes shown first, followed by
    subclasses with "→ also:" notation to indicate they inherit conformance.
"""

from __future__ import annotations

import lldb
import os
import re
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

from objc_utils import unquote_string

# Import class cache from objc_cls if available (for reuse)
try:
    from objc_cls import _class_cache, get_all_classes, matches_pattern
except ImportError:
    _class_cache = {}
    get_all_classes = None
    matches_pattern = None


def _matches_pattern(name: str, pattern: Optional[str]) -> bool:
    """
    Check if name matches the pattern.
    Supports wildcards: * (any characters) and ? (single character)
    Without wildcards: exact match (case-sensitive)
    """
    if pattern is None:
        return True

    # Check if pattern contains wildcard characters
    has_wildcards = '*' in pattern or '?' in pattern

    if has_wildcards:
        # Convert wildcard pattern to regex
        regex_pattern = re.escape(pattern)
        regex_pattern = regex_pattern.replace(r'\*', '.*')
        regex_pattern = regex_pattern.replace(r'\?', '.')
        regex_pattern = f'^{regex_pattern}$'
        try:
            return bool(re.match(regex_pattern, name, re.IGNORECASE))
        except re.error:
            return name == pattern
    else:
        # Exact matching (case-sensitive)
        return name == pattern


def get_all_protocols(
    frame: lldb.SBFrame,
    pattern: Optional[str] = None
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Get all registered Objective-C protocols.

    Args:
        frame: LLDB frame for expression evaluation
        pattern: Optional pattern to filter protocols

    Returns:
        Tuple of (protocol_names, timing_dict)
    """
    start_time = time.time()
    timing = {
        'total': 0,
        'expression_count': 0,
        'memory_read_count': 0
    }

    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()

    # Allocate count variable
    count_var_expr = '(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)
    timing['expression_count'] += 1

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        return [], timing

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Get protocol list
    proto_list_expr = f'(void *)objc_copyProtocolList((unsigned int *)0x{count_var_ptr:x})'
    proto_list_result = frame.EvaluateExpression(proto_list_expr)
    timing['expression_count'] += 1

    if not proto_list_result.IsValid() or proto_list_result.GetError().Fail():
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    proto_list_ptr = proto_list_result.GetValueAsUnsigned()

    # Read the count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)
    timing['expression_count'] += 1

    if not count_read_result.IsValid() or count_read_result.GetError().Fail():
        if proto_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{proto_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    proto_count = count_read_result.GetValueAsUnsigned()

    if proto_count == 0 or proto_list_ptr == 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    # Bulk read protocol pointer array
    array_size = proto_count * pointer_size
    error = lldb.SBError()
    proto_array_bytes = process.ReadMemory(proto_list_ptr, array_size, error)
    timing['memory_read_count'] += 1

    if not error.Success():
        if proto_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{proto_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], timing

    # Parse protocol pointers
    if pointer_size == 8:
        format_str = f'{proto_count}Q'
    else:
        format_str = f'{proto_count}I'

    proto_pointers = struct.unpack(format_str, proto_array_bytes)

    # Get protocol names - batch them for efficiency
    protocol_names = []
    batch_size = 50

    for batch_start in range(0, len(proto_pointers), batch_size):
        batch_end = min(batch_start + batch_size, len(proto_pointers))
        batch = proto_pointers[batch_start:batch_end]

        # Build batch expression
        batch_expr = f'''
(void *)(^{{
    void **info = (void **)malloc({len(batch) * 8});
    if (!info) return (void *)0;
'''
        for i, proto_ptr in enumerate(batch):
            if proto_ptr != 0:
                batch_expr += f'    info[{i}] = (void *)protocol_getName((void *)0x{proto_ptr:x});\n'
            else:
                batch_expr += f'    info[{i}] = (void *)0;\n'

        batch_expr += '''    return (void *)info;
}())
'''
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if batch_result.IsValid() and not batch_result.GetError().Fail():
            info_ptr = batch_result.GetValueAsUnsigned()
            if info_ptr != 0:
                # Read pointers
                info_bytes = process.ReadMemory(info_ptr, len(batch) * pointer_size, error)
                timing['memory_read_count'] += 1

                if error.Success():
                    if pointer_size == 8:
                        name_ptrs = struct.unpack(f'{len(batch)}Q', info_bytes)
                    else:
                        name_ptrs = struct.unpack(f'{len(batch)}I', info_bytes)

                    for name_ptr in name_ptrs:
                        if name_ptr != 0:
                            proto_name = process.ReadCStringFromMemory(name_ptr, 256, error)
                            if error.Success() and proto_name:
                                if pattern is None or _matches_pattern(proto_name, pattern):
                                    protocol_names.append(proto_name)

                frame.EvaluateExpression(f'(void)free((void *)0x{info_ptr:x})')
                timing['expression_count'] += 1
        else:
            # Fallback to individual calls
            for proto_ptr in batch:
                if proto_ptr == 0:
                    continue
                name_expr = f'(const char *)protocol_getName((void *)0x{proto_ptr:x})'
                name_result = frame.EvaluateExpression(name_expr)
                timing['expression_count'] += 1

                if name_result.IsValid() and not name_result.GetError().Fail():
                    proto_name = name_result.GetSummary()
                    if proto_name:
                        proto_name = unquote_string(proto_name)
                        if pattern is None or _matches_pattern(proto_name, pattern):
                            protocol_names.append(proto_name)

    # Clean up
    if proto_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{proto_list_ptr:x})')
        timing['expression_count'] += 1
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
    timing['expression_count'] += 1

    timing['total'] = time.time() - start_time

    return sorted(protocol_names), timing


def get_protocol_pointer(frame: lldb.SBFrame, protocol_name: str) -> int:
    """
    Get the Protocol pointer for a given protocol name.

    Args:
        frame: LLDB frame for expression evaluation
        protocol_name: Name of the protocol

    Returns:
        Protocol pointer address, or 0 if not found
    """
    proto_expr = f'(void *)objc_getProtocol("{protocol_name}")'
    proto_result = frame.EvaluateExpression(proto_expr)

    if not proto_result.IsValid() or proto_result.GetError().Fail():
        return 0

    return proto_result.GetValueAsUnsigned()


def check_class_conforms_to_protocol(
    frame: lldb.SBFrame,
    class_ptr: int,
    protocol_ptr: int
) -> bool:
    """
    Check if a class conforms to a protocol.

    Args:
        frame: LLDB frame for expression evaluation
        class_ptr: Class pointer address
        protocol_ptr: Protocol pointer address

    Returns:
        True if class conforms to protocol
    """
    if class_ptr == 0 or protocol_ptr == 0:
        return False

    conforms_expr = f'(BOOL)class_conformsToProtocol((Class)0x{class_ptr:x}, (void *)0x{protocol_ptr:x})'
    conforms_result = frame.EvaluateExpression(conforms_expr)

    if not conforms_result.IsValid() or conforms_result.GetError().Fail():
        return False

    return conforms_result.GetValueAsUnsigned() != 0


def get_class_superclass(frame: lldb.SBFrame, class_ptr: int) -> int:
    """
    Get the superclass pointer for a class.

    Args:
        frame: LLDB frame for expression evaluation
        class_ptr: Class pointer address

    Returns:
        Superclass pointer, or 0 if none
    """
    if class_ptr == 0:
        return 0

    super_expr = f'(void *)class_getSuperclass((Class)0x{class_ptr:x})'
    super_result = frame.EvaluateExpression(super_expr)

    if not super_result.IsValid() or super_result.GetError().Fail():
        return 0

    return super_result.GetValueAsUnsigned()


def find_conforming_classes(
    frame: lldb.SBFrame,
    protocol_name: str,
    direct_only: bool = False,
    force_reload: bool = False,
    verbose: bool = False
) -> Tuple[List[Tuple[str, bool]], Dict[str, Any], int]:
    """
    Find all classes that conform to a protocol.

    Args:
        frame: LLDB frame for expression evaluation
        protocol_name: Name of the protocol to check
        direct_only: If True, only return classes that directly declare conformance
        force_reload: If True, bypass class cache
        verbose: If True, print progress

    Returns:
        Tuple of (conforming_classes, timing_dict, total_classes_scanned)
        conforming_classes is a list of (class_name, is_direct) tuples
    """
    start_time = time.time()
    timing = {
        'total': 0,
        'class_enum': 0,
        'conformance_check': 0,
        'expression_count': 0,
        'memory_read_count': 0
    }

    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()

    # Get protocol pointer
    protocol_ptr = get_protocol_pointer(frame, protocol_name)
    timing['expression_count'] += 1

    if protocol_ptr == 0:
        timing['total'] = time.time() - start_time
        return [], timing, 0

    # Get all classes (reuse ocls infrastructure if available)
    class_enum_start = time.time()

    if get_all_classes is not None:
        # Use ocls class cache
        class_names, cls_timing, class_count, from_cache = get_all_classes(
            frame, pattern=None, force_reload=force_reload
        )
        timing['expression_count'] += cls_timing.get('expression_count', 0)
        timing['memory_read_count'] += cls_timing.get('memory_read_count', 0)
    else:
        # Fallback: enumerate classes ourselves
        class_names, class_count = _enumerate_all_classes(frame, timing)

    timing['class_enum'] = time.time() - class_enum_start

    if verbose:
        print(f"Scanning {len(class_names)} classes for {protocol_name} conformance...")

    # Build class name -> pointer map for efficiency
    conformance_start = time.time()
    conforming_classes = []

    # First pass: find all conforming classes
    # We need class pointers for conformance check
    class_ptr_map = {}

    # Batch get class pointers
    batch_size = 50
    for batch_start in range(0, len(class_names), batch_size):
        batch_end = min(batch_start + batch_size, len(class_names))
        batch = class_names[batch_start:batch_end]

        # Build batch expression to get class pointers
        batch_expr = f'''
(void *)(^{{
    void **ptrs = (void **)malloc({len(batch) * 8});
    if (!ptrs) return (void *)0;
'''
        for i, class_name in enumerate(batch):
            batch_expr += f'    ptrs[{i}] = (void *)NSClassFromString(@"{class_name}");\n'

        batch_expr += '''    return (void *)ptrs;
}())
'''
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if batch_result.IsValid() and not batch_result.GetError().Fail():
            ptrs_addr = batch_result.GetValueAsUnsigned()
            if ptrs_addr != 0:
                error = lldb.SBError()
                ptrs_bytes = process.ReadMemory(ptrs_addr, len(batch) * pointer_size, error)
                timing['memory_read_count'] += 1

                if error.Success():
                    if pointer_size == 8:
                        ptrs = struct.unpack(f'{len(batch)}Q', ptrs_bytes)
                    else:
                        ptrs = struct.unpack(f'{len(batch)}I', ptrs_bytes)

                    for class_name, class_ptr in zip(batch, ptrs):
                        if class_ptr != 0:
                            class_ptr_map[class_name] = class_ptr

                frame.EvaluateExpression(f'(void)free((void *)0x{ptrs_addr:x})')
                timing['expression_count'] += 1

    # Now check conformance in batches
    class_names_with_ptrs = [(name, ptr) for name, ptr in class_ptr_map.items()]

    for batch_start in range(0, len(class_names_with_ptrs), batch_size):
        batch_end = min(batch_start + batch_size, len(class_names_with_ptrs))
        batch = class_names_with_ptrs[batch_start:batch_end]

        # Build batch expression to check conformance
        batch_expr = f'''
(void *)(^{{
    unsigned char *results = (unsigned char *)malloc({len(batch)});
    if (!results) return (void *)0;
'''
        for i, (class_name, class_ptr) in enumerate(batch):
            batch_expr += f'    results[{i}] = (unsigned char)class_conformsToProtocol((Class)0x{class_ptr:x}, (void *)0x{protocol_ptr:x});\n'

        batch_expr += '''    return (void *)results;
}())
'''
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if batch_result.IsValid() and not batch_result.GetError().Fail():
            results_addr = batch_result.GetValueAsUnsigned()
            if results_addr != 0:
                error = lldb.SBError()
                results_bytes = process.ReadMemory(results_addr, len(batch), error)
                timing['memory_read_count'] += 1

                if error.Success():
                    for i, (class_name, class_ptr) in enumerate(batch):
                        if results_bytes[i] != 0:
                            conforming_classes.append((class_name, class_ptr))

                frame.EvaluateExpression(f'(void)free((void *)0x{results_addr:x})')
                timing['expression_count'] += 1

        if verbose and batch_start > 0 and batch_start % 500 == 0:
            print(f"  Progress: {batch_start}/{len(class_names_with_ptrs)} classes checked...")

    # If direct_only, filter to classes where superclass doesn't conform
    if direct_only:
        direct_conforming = []
        for class_name, class_ptr in conforming_classes:
            super_ptr = get_class_superclass(frame, class_ptr)
            timing['expression_count'] += 1

            if super_ptr == 0:
                # No superclass - this is direct
                direct_conforming.append((class_name, True))
            else:
                # Check if superclass conforms
                super_conforms = check_class_conforms_to_protocol(frame, super_ptr, protocol_ptr)
                timing['expression_count'] += 1

                if not super_conforms:
                    # Superclass doesn't conform - this is direct
                    direct_conforming.append((class_name, True))
        conforming_classes = direct_conforming
    else:
        # Mark each class as direct or inherited
        result_classes = []
        for class_name, class_ptr in conforming_classes:
            super_ptr = get_class_superclass(frame, class_ptr)
            timing['expression_count'] += 1

            if super_ptr == 0:
                is_direct = True
            else:
                super_conforms = check_class_conforms_to_protocol(frame, super_ptr, protocol_ptr)
                timing['expression_count'] += 1
                is_direct = not super_conforms

            result_classes.append((class_name, is_direct))
        conforming_classes = result_classes

    timing['conformance_check'] = time.time() - conformance_start
    timing['total'] = time.time() - start_time

    return conforming_classes, timing, class_count


def _enumerate_all_classes(frame: lldb.SBFrame, timing: Dict[str, Any]) -> Tuple[List[str], int]:
    """
    Fallback class enumeration when ocls is not available.
    """
    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()

    # Allocate count variable
    count_var_expr = '(unsigned int *)malloc(sizeof(unsigned int))'
    count_var_result = frame.EvaluateExpression(count_var_expr)
    timing['expression_count'] += 1

    if not count_var_result.IsValid() or count_var_result.GetError().Fail():
        return [], 0

    count_var_ptr = count_var_result.GetValueAsUnsigned()

    # Get class list
    class_list_expr = f'(void *)objc_copyClassList((unsigned int *)0x{count_var_ptr:x})'
    class_list_result = frame.EvaluateExpression(class_list_expr)
    timing['expression_count'] += 1

    if not class_list_result.IsValid() or class_list_result.GetError().Fail():
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], 0

    class_list_ptr = class_list_result.GetValueAsUnsigned()

    # Read count
    count_read_expr = f'(unsigned int)(*(unsigned int *)0x{count_var_ptr:x})'
    count_read_result = frame.EvaluateExpression(count_read_expr)
    timing['expression_count'] += 1

    class_count = count_read_result.GetValueAsUnsigned() if count_read_result.IsValid() else 0

    if class_count == 0:
        if class_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], 0

    # Bulk read class pointer array
    array_size = class_count * pointer_size
    error = lldb.SBError()
    class_array_bytes = process.ReadMemory(class_list_ptr, array_size, error)
    timing['memory_read_count'] += 1

    if not error.Success():
        if class_list_ptr != 0:
            frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
            timing['expression_count'] += 1
        frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
        timing['expression_count'] += 1
        return [], class_count

    if pointer_size == 8:
        class_pointers = struct.unpack(f'{class_count}Q', class_array_bytes)
    else:
        class_pointers = struct.unpack(f'{class_count}I', class_array_bytes)

    # Get class names in batches
    class_names = []
    batch_size = 50

    for batch_start in range(0, len(class_pointers), batch_size):
        batch_end = min(batch_start + batch_size, len(class_pointers))
        batch = class_pointers[batch_start:batch_end]

        batch_expr = f'''
(void *)(^{{
    void **info = (void **)malloc({len(batch) * 8});
    if (!info) return (void *)0;
'''
        for i, class_ptr in enumerate(batch):
            if class_ptr != 0:
                batch_expr += f'    info[{i}] = (void *)class_getName((Class)0x{class_ptr:x});\n'
            else:
                batch_expr += f'    info[{i}] = (void *)0;\n'

        batch_expr += '''    return (void *)info;
}())
'''
        batch_result = frame.EvaluateExpression(batch_expr)
        timing['expression_count'] += 1

        if batch_result.IsValid() and not batch_result.GetError().Fail():
            info_ptr = batch_result.GetValueAsUnsigned()
            if info_ptr != 0:
                info_bytes = process.ReadMemory(info_ptr, len(batch) * pointer_size, error)
                timing['memory_read_count'] += 1

                if error.Success():
                    if pointer_size == 8:
                        name_ptrs = struct.unpack(f'{len(batch)}Q', info_bytes)
                    else:
                        name_ptrs = struct.unpack(f'{len(batch)}I', info_bytes)

                    for name_ptr in name_ptrs:
                        if name_ptr != 0:
                            class_name = process.ReadCStringFromMemory(name_ptr, 256, error)
                            if error.Success() and class_name:
                                class_names.append(class_name)

                frame.EvaluateExpression(f'(void)free((void *)0x{info_ptr:x})')
                timing['expression_count'] += 1

    # Clean up
    if class_list_ptr != 0:
        frame.EvaluateExpression(f'(void)free((void *)0x{class_list_ptr:x})')
        timing['expression_count'] += 1
    frame.EvaluateExpression(f'(void)free((void *)0x{count_var_ptr:x})')
    timing['expression_count'] += 1

    return class_names, class_count


def group_classes_by_inheritance(
    frame: lldb.SBFrame,
    conforming_classes: List[Tuple[str, bool]]
) -> List[Tuple[str, List[str], bool]]:
    """
    Group conforming classes by inheritance.

    Args:
        frame: LLDB frame for expression evaluation
        conforming_classes: List of (class_name, is_direct) tuples

    Returns:
        List of (base_class, [subclasses], is_direct) tuples
    """
    if not conforming_classes:
        return []

    # Build set of conforming class names for quick lookup
    conforming_set = {name for name, _ in conforming_classes}
    direct_map = {name: is_direct for name, is_direct in conforming_classes}

    # Build superclass map using batching to avoid timeout
    process = frame.GetThread().GetProcess()
    pointer_size = frame.GetModule().GetAddressByteSize()
    superclass_map = {}

    # First, get all class pointers in batches
    class_ptr_map = {}
    batch_size = 50
    class_names = [name for name, _ in conforming_classes]

    for batch_start in range(0, len(class_names), batch_size):
        batch_end = min(batch_start + batch_size, len(class_names))
        batch = class_names[batch_start:batch_end]

        # Build batch expression to get class pointers and superclass names
        batch_expr = f'''
(void *)(^{{
    void **ptrs = (void **)malloc({len(batch) * 2 * 8});
    if (!ptrs) return (void *)0;
'''
        for i, class_name in enumerate(batch):
            batch_expr += f'''    {{
        Class cls = NSClassFromString(@"{class_name}");
        ptrs[{i*2}] = (void *)cls;
        ptrs[{i*2+1}] = cls ? (void *)class_getName(class_getSuperclass(cls)) : (void *)0;
    }}
'''

        batch_expr += '''    return (void *)ptrs;
}())
'''
        batch_result = frame.EvaluateExpression(batch_expr)

        if batch_result.IsValid() and not batch_result.GetError().Fail():
            ptrs_addr = batch_result.GetValueAsUnsigned()
            if ptrs_addr != 0:
                error = lldb.SBError()
                ptrs_bytes = process.ReadMemory(ptrs_addr, len(batch) * 2 * pointer_size, error)

                if error.Success():
                    if pointer_size == 8:
                        ptrs = struct.unpack(f'{len(batch) * 2}Q', ptrs_bytes)
                    else:
                        ptrs = struct.unpack(f'{len(batch) * 2}I', ptrs_bytes)

                    for i, class_name in enumerate(batch):
                        class_ptr = ptrs[i*2]
                        super_name_ptr = ptrs[i*2+1]

                        if class_ptr != 0:
                            class_ptr_map[class_name] = class_ptr

                        if super_name_ptr != 0:
                            super_name = process.ReadCStringFromMemory(super_name_ptr, 256, error)
                            if error.Success() and super_name:
                                superclass_map[class_name] = super_name

                frame.EvaluateExpression(f'(void)free((void *)0x{ptrs_addr:x})')

    # Find "root" conforming classes (those whose superclass doesn't conform)
    root_classes = []
    subclass_map = {}  # maps root -> [subclasses]

    for class_name, is_direct in conforming_classes:
        super_name = superclass_map.get(class_name)

        if super_name and super_name in conforming_set:
            # This class has a conforming superclass
            # Find the root conforming ancestor
            root = super_name
            visited = {class_name}
            while root in superclass_map and superclass_map[root] in conforming_set:
                if root in visited:
                    break
                visited.add(root)
                root = superclass_map[root]

            if root not in subclass_map:
                subclass_map[root] = []
            subclass_map[root].append(class_name)
        else:
            # This is a root conforming class
            root_classes.append(class_name)

    # Build result
    result = []
    for root in sorted(root_classes):
        subclasses = sorted(subclass_map.get(root, []))
        is_direct = direct_map.get(root, True)
        result.append((root, subclasses, is_direct))

    return result


def find_objc_protocol_conformance(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Find Objective-C classes that conform to a protocol.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse arguments
    args = command.strip().split()

    list_mode = '--list' in args
    direct_only = '--direct' in args
    force_reload = '--reload' in args
    verbose = '--verbose' in args

    # Remove flags from args
    pattern_args = [a for a in args if not a.startswith('--')]

    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    if list_mode:
        # List protocols mode
        pattern = pattern_args[0] if pattern_args else None
        protocols, timing = get_all_protocols(frame, pattern)

        if not protocols:
            if pattern:
                print(f"No protocols found matching: {pattern}")
            else:
                print("No protocols found")
        else:
            if pattern:
                print(f"Protocols matching '{pattern}':")
            else:
                print("Registered protocols:")

            for proto in protocols:
                print(f"  {proto}")

            print(f"\nTotal: {len(protocols)} protocol(s)")
            print(f"[{timing['total']:.2f}s]")

        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Conformance check mode
    if not pattern_args:
        print("Usage: oprotos <protocol> [--direct] [--reload] [--verbose]")
        print("       oprotos --list [pattern]")
        print("")
        print("Examples:")
        print("  oprotos NSCoding              # All classes conforming to NSCoding")
        print("  oprotos NSCopying --direct    # Only direct conformance")
        print("  oprotos *Delegate             # Protocols matching wildcard")
        print("  oprotos --list                # List all protocols")
        print("  oprotos --list NS*            # List NS* protocols")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    protocol_pattern = pattern_args[0]

    # Check if it's a wildcard pattern
    has_wildcards = '*' in protocol_pattern or '?' in protocol_pattern

    if has_wildcards:
        # Wildcard patterns: list matching protocols (conformance check would be too slow)
        matching_protocols, proto_timing = get_all_protocols(frame, protocol_pattern)

        if not matching_protocols:
            print(f"No protocols found matching: {protocol_pattern}")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

        print(f"Protocols matching '{protocol_pattern}':")
        for proto in matching_protocols:
            print(f"  {proto}")

        print(f"\nTotal: {len(matching_protocols)} protocol(s) matching '{protocol_pattern}'")
        print(f"[{proto_timing['total']:.2f}s]")
        print(f"\n\033[90mTip: Use a specific protocol name to find conforming classes, e.g.:\033[0m")
        if matching_protocols:
            print(f"\033[90m  oprotos {matching_protocols[0]}\033[0m")

        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return
    else:
        # Single protocol lookup
        protocol_ptr = get_protocol_pointer(frame, protocol_pattern)

        if protocol_ptr == 0:
            print(f"Protocol not found: {protocol_pattern}")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

        conforming, timing, scanned = find_conforming_classes(
            frame, protocol_pattern, direct_only, force_reload, verbose
        )

        if not conforming:
            print(f"No classes conform to: {protocol_pattern}")
        else:
            # Group by inheritance
            grouped = group_classes_by_inheritance(frame, conforming)

            conformance_type = "directly conform" if direct_only else "conform"
            print(f"Classes that {conformance_type} to {protocol_pattern}:")

            for base_class, subclasses, _is_direct in grouped:
                print(f"  {base_class}")
                if subclasses:
                    # Show subclasses with dim formatting
                    subclass_str = ', '.join(subclasses[:5])
                    if len(subclasses) > 5:
                        subclass_str += f", ... (+{len(subclasses) - 5} more)"
                    print(f"    \033[90m→ also: {subclass_str}\033[0m")

            print(f"\nTotal: {len(conforming)} class(es) {conformance_type} to {protocol_pattern}")
            print(f"[Scanned {scanned:,} classes | {timing['total']:.2f}s]")

            if verbose:
                print(f"\n  Timing breakdown:")
                print(f"    Class enumeration: {timing.get('class_enum', 0):.2f}s")
                print(f"    Conformance check: {timing.get('conformance_check', 0):.2f}s")
                print(f"    Expressions: {timing.get('expression_count', 0):,}")
                print(f"    Memory reads: {timing.get('memory_read_count', 0):,}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Find Objective-C classes that conform to a protocol. '
        'Usage: oprotos <protocol> [--direct] [--reload] [--verbose] | oprotos --list [pattern]" '
        '-f objc_protos.find_objc_protocol_conformance oprotos'
    )
    print(f"[lldb-objc v{__version__}] Protocol conformance finder 'oprotos' has been installed.")
    print("Usage: oprotos <protocol> [--direct] or oprotos --list [pattern]")
