#!/usr/bin/env python3
"""
LLDB script for querying keychain items accessible to the current process.

Usage:
    okeychain list              # List all accessible keychain items
    okeychain list --filter=<query>  # Filter by access group or account
    okeychain list --verbose    # Show detailed debug info
    okeychain extract <file>    # Extract all keychain items to XML plist file
    okeychain extract <file> --filter=<query>  # Extract filtered items
"""

from __future__ import annotations

import lldb
import os
import plistlib
import sys
from typing import Any, Dict, List, Optional, Tuple

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Guard against double initialization
_initialized = False

# Keychain class constants
KEYCHAIN_CLASSES = {
    "kSecClassGenericPassword": "genp",
    "kSecClassInternetPassword": "inet",
    "kSecClassCertificate": "cert",
    "kSecClassKey": "keys",
    "kSecClassIdentity": "idnt",
}


def _extract_nsdata_bytes(target: lldb.SBTarget, nsdata_value: lldb.SBValue, verbose: bool = False) -> Optional[bytes]:
    """
    Extract raw bytes from an NSData object.

    Returns: bytes object or None if extraction fails
    """
    if not nsdata_value.IsValid():
        return None

    # Get the bytes pointer and length
    expr = f"""
    @import Foundation;
    NSData *data_obj = (NSData *){nsdata_value.GetValueAsUnsigned()};
    (void *)[data_obj bytes];
    """

    bytes_result = target.EvaluateExpression(expr)
    if not bytes_result.IsValid() or bytes_result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to get bytes pointer: {bytes_result.GetError()}")
        return None

    bytes_ptr = bytes_result.GetValueAsUnsigned()

    # Get length
    expr_len = f"""
    @import Foundation;
    NSData *data_obj = (NSData *){nsdata_value.GetValueAsUnsigned()};
    (unsigned long)[data_obj length];
    """

    len_result = target.EvaluateExpression(expr_len)
    if not len_result.IsValid() or len_result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to get data length: {len_result.GetError()}")
        return None

    data_length = len_result.GetValueAsUnsigned()

    if data_length == 0 or bytes_ptr == 0:
        return b""

    # Read the raw bytes from memory
    process = target.GetProcess()
    error = lldb.SBError()
    data = process.ReadMemory(bytes_ptr, data_length, error)

    if error.Fail():
        if verbose:
            print(f"[DEBUG] Failed to read memory: {error}")
        return None

    return data


def _parse_keychain_dict(
    target: lldb.SBTarget, dict_value: lldb.SBValue, class_value: str, verbose: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Parse an NSDictionary from keychain query into a Python dict with proper types.

    Returns: dictionary with parsed fields or None if parsing fails
    """
    if not dict_value.IsValid():
        if verbose:
            print("[DEBUG] dict_value is invalid")
        return None

    result_dict = {"class": class_value}

    # For now, use the object description as a fallback
    # This ensures the command doesn't hang during the transition
    description = dict_value.GetObjectDescription()
    if description:
        result_dict["_raw_description"] = description

    try:
        # Get all keys from the dictionary
        expr = f"""
        @import Foundation;
        NSDictionary *dict = (NSDictionary *){dict_value.GetValueAsUnsigned()};
        (NSArray *)[dict allKeys];
        """

        keys_result = target.EvaluateExpression(expr)
        if not keys_result.IsValid() or keys_result.GetError().Fail():
            if verbose:
                error_msg = keys_result.GetError().GetCString() if keys_result.IsValid() else "Invalid result"
                print(f"[DEBUG] Failed to get dictionary keys: {error_msg}")
            # Return the dict with description fallback
            return result_dict

        num_keys = keys_result.GetNumChildren()
        if verbose:
            print(f"[DEBUG] Dictionary has {num_keys} keys")

        # Limit the number of keys we process to avoid hanging
        max_keys = min(num_keys, 50)  # Safety limit

        # Iterate through each key and extract the value
        for i in range(max_keys):
            key_value = keys_result.GetChildAtIndex(i)
            if not key_value.IsValid():
                continue

            # Get the key as a string
            key_str = key_value.GetSummary()
            if key_str:
                # Remove quotes from the string summary
                key_str = key_str.strip('"')
            else:
                continue

            # Escape special characters in the key string
            key_str_escaped = key_str.replace('"', '\\"')

            # Get the value for this key
            expr_val = f"""
            @import Foundation;
            NSDictionary *dict = (NSDictionary *){dict_value.GetValueAsUnsigned()};
            (id)[dict objectForKey:@"{key_str_escaped}"];
            """

            val_result = target.EvaluateExpression(expr_val)
            if not val_result.IsValid():
                if verbose:
                    print(f"[DEBUG] Failed to get value for key '{key_str}'")
                continue

            # Determine the type and extract accordingly
            type_name = val_result.GetTypeName()

            if "NSData" in type_name or "NSCFData" in type_name:
                # Extract raw bytes
                data_bytes = _extract_nsdata_bytes(target, val_result, verbose)
                if data_bytes is not None:
                    result_dict[key_str] = data_bytes
                else:
                    # Fallback to description if extraction fails
                    result_dict[key_str] = val_result.GetObjectDescription() or ""
            elif "NSString" in type_name or "NSCFString" in type_name:
                # Extract string value
                string_val = val_result.GetSummary()
                if string_val:
                    # Remove quotes
                    string_val = string_val.strip('"')
                    result_dict[key_str] = string_val
                else:
                    result_dict[key_str] = ""
            elif "NSNumber" in type_name or "NSCFNumber" in type_name:
                # Extract number value
                num_val = val_result.GetValueAsUnsigned()
                result_dict[key_str] = num_val
            else:
                # For other types, use the object description
                desc = val_result.GetObjectDescription()
                if desc:
                    result_dict[key_str] = desc
                elif verbose:
                    print(f"[DEBUG] Unknown type for key '{key_str}': {type_name}")

    except Exception as e:
        if verbose:
            print(f"[DEBUG] Exception during dict parsing: {e}")
        # Return the dict with description fallback
        pass

    return result_dict


def _query_keychain_class(
    frame: lldb.SBFrame, class_name: str, class_value: str, verbose: bool = False
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Query a single keychain class for all accessible items.

    Returns: (items_list, error)
    """
    target = frame.GetThread().GetProcess().GetTarget()

    if verbose:
        print(f"[DEBUG] Querying {class_name} ({class_value})...")

    # Build the query dictionary
    # We want: all items, with attributes, data, and no limit
    expr = f"""
    @import Foundation;
    @import Security;

    NSMutableDictionary *query_{class_value} = [NSMutableDictionary dictionary];
    query_{class_value}[(id)kSecClass] = (id){class_name};
    query_{class_value}[(id)kSecReturnAttributes] = @YES;
    query_{class_value}[(id)kSecReturnData] = @YES;
    query_{class_value}[(id)kSecMatchLimit] = (id)kSecMatchLimitAll;

    CFTypeRef result_{class_value} = NULL;
    OSStatus status_{class_value} = SecItemCopyMatching((CFDictionaryRef)query_{class_value}, &result_{class_value});

    (NSArray *)result_{class_value};
    """

    result = target.EvaluateExpression(expr)

    if not result.IsValid():
        if verbose:
            print(f"[DEBUG] {class_name}: Invalid result")
        return None, None  # No items, not an error

    error = result.GetError()
    if error.Fail():
        error_msg = error.GetCString()
        if verbose:
            print(f"[DEBUG] {class_name}: {error_msg}")
        # errSecItemNotFound is not an error, just means no items
        if "errSecItemNotFound" in error_msg or "-25300" in error_msg:
            return None, None
        return None, f"Query failed for {class_name}: {error_msg}"

    # Check if we got an array back
    type_name = result.GetTypeName()
    if "NSArray" not in type_name and "NSCFArray" not in type_name:
        if verbose:
            print(f"[DEBUG] {class_name}: No items (not an array)")
        return None, None

    # Get the number of items
    num_children = result.GetNumChildren()
    if num_children == 0:
        if verbose:
            print(f"[DEBUG] {class_name}: No items (empty array)")
        return None, None

    if verbose:
        print(f"[DEBUG] {class_name}: Found {num_children} items")

    items = []
    for i in range(num_children):
        child = result.GetChildAtIndex(i)
        if child.IsValid():
            # Parse the dictionary into a proper Python dict
            item_dict = _parse_keychain_dict(target, child, class_value, verbose)
            if item_dict:
                items.append(item_dict)

    return items, None


def _format_keychain_item(item_dict: Dict[str, Any], verbose: bool = False) -> str:
    """
    Format a keychain item for display.

    Extracts key fields like access group (agrp), account (acct), and data.
    """
    class_value = item_dict.get("class", "unknown")

    # Build output lines
    lines = []
    lines.append(f"Class: {class_value}")

    # Common fields to look for in order
    fields = ["agrp", "acct", "svce", "labl", "v_Data"]

    for field in fields:
        if field in item_dict:
            value = item_dict[field]

            # Format based on type
            if isinstance(value, bytes):
                # Show truncated hex representation for bytes
                hex_str = value.hex()
                if len(hex_str) > 64:
                    display_value = hex_str[:64] + "..."
                else:
                    display_value = hex_str
                lines.append(f"  {field}: {display_value} ({len(value)} bytes)")
            elif isinstance(value, int):
                lines.append(f"  {field}: {value}")
            elif isinstance(value, str):
                # Truncate long strings
                if len(value) > 64:
                    display_value = value[:64] + "..."
                else:
                    display_value = value
                lines.append(f"  {field}: {display_value}")
            else:
                lines.append(f"  {field}: {value}")

    # Show any other fields not in the common list, excluding internal fields
    for key, value in item_dict.items():
        if key not in fields and key != "class" and not key.startswith("_"):
            if isinstance(value, bytes):
                lines.append(f"  {key}: <{len(value)} bytes>")
            else:
                lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def list_keychain_items(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    List all keychain items accessible to the current process.

    Usage:
        okeychain list              # List all accessible keychain items
        okeychain list --filter=<query>  # Filter by access group or account
        okeychain list --verbose    # Show detailed debug info
    """
    # Parse flags
    verbose = "--verbose" in command or "-v" in command
    filter_query = None

    # Extract filter argument
    if "--filter=" in command:
        start = command.find("--filter=") + len("--filter=")
        rest = command[start:].strip()
        # Get the filter value (up to next space or end)
        filter_query = rest.split()[0] if rest else None

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Get the current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Query all keychain classes
    all_items = []
    for class_name, class_value in KEYCHAIN_CLASSES.items():
        items, error = _query_keychain_class(frame, class_name, class_value, verbose)

        if error:
            print(f"Warning: {error}")
            continue

        if items:
            all_items.extend(items)

    if not all_items:
        print("No keychain items found.")
        print("\nThis could mean:")
        print("  1. The app has no keychain items")
        print("  2. The keychain is locked")
        print("  3. The app lacks necessary entitlements")
        print("\nUse 'oentitlements' to check keychain-access-groups")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Filter if requested
    if filter_query:
        filtered_items = []
        for item in all_items:
            # Check if filter matches any field value
            match = False
            for key, value in item.items():
                if key == "class" or key.startswith("_"):
                    continue
                # Convert value to string for searching
                if isinstance(value, bytes):
                    # Search in hex representation
                    value_str = value.hex()
                else:
                    value_str = str(value)

                if filter_query.lower() in value_str.lower():
                    match = True
                    break
            if match:
                filtered_items.append(item)
        all_items = filtered_items

        if not all_items:
            print(f"No keychain items matching filter: {filter_query}")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

    # Display the items
    print(f"Found {len(all_items)} keychain item(s)\n")

    for i, item in enumerate(all_items):
        print(f"Item {i + 1}:")
        if verbose:
            # Show all fields in verbose mode
            for key, value in item.items():
                if isinstance(value, bytes):
                    print(f"  {key}: {value.hex()} ({len(value)} bytes)")
                else:
                    print(f"  {key}: {value}")
        else:
            # Show formatted output
            print(_format_keychain_item(item, verbose))
        print()  # Blank line between items

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def extract_keychain_items(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Extract all keychain items and save them to an XML plist file.

    Usage:
        okeychain extract <output_file>  # Extract all keychain items to file
        okeychain extract <output_file> --filter=<query>  # Extract filtered items
        okeychain extract <output_file> --verbose  # Show debug info during extraction
    """
    # Parse flags
    verbose = "--verbose" in command or "-v" in command
    filter_query = None

    # Extract filter argument
    if "--filter=" in command:
        start = command.find("--filter=") + len("--filter=")
        rest = command[start:].strip()
        filter_query = rest.split()[0] if rest else None
        # Remove filter from command to get the file path
        command = command.replace(f"--filter={filter_query}", "").strip()

    # Remove verbose flag from command
    command = command.replace("--verbose", "").replace("-v", "").strip()

    # Get the output file path
    args = command.strip().split()
    if not args:
        result.SetError("Usage: okeychain extract <output_file> [--filter=<query>] [--verbose]")
        return

    output_file = args[0]

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Get the current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Query all keychain classes
    all_items = []
    for class_name, class_value in KEYCHAIN_CLASSES.items():
        items, error = _query_keychain_class(frame, class_name, class_value, verbose)

        if error:
            print(f"Warning: {error}")
            continue

        if items:
            all_items.extend(items)

    if not all_items:
        print("No keychain items found to extract.")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Filter if requested
    if filter_query:
        filtered_items = []
        for item in all_items:
            # Check if filter matches any field value
            match = False
            for key, value in item.items():
                if key == "class" or key.startswith("_"):
                    continue
                # Convert value to string for searching
                if isinstance(value, bytes):
                    # Search in hex representation
                    value_str = value.hex()
                else:
                    value_str = str(value)

                if filter_query.lower() in value_str.lower():
                    match = True
                    break
            if match:
                filtered_items.append(item)
        all_items = filtered_items

        if not all_items:
            print(f"No keychain items matching filter: {filter_query}")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

    # Convert items to plist format
    # The items are already dictionaries with proper types (bytes, str, int)
    # plistlib will handle serialization correctly
    plist_items = []
    for i, item in enumerate(all_items):
        # Add an index field to each item
        item_with_index = {"index": i + 1}
        # Copy all fields from the original item
        item_with_index.update(item)
        plist_items.append(item_with_index)

    # Create the full plist structure
    plist_data = {
        "count": len(all_items),
        "items": plist_items,
        "extracted_by": "lldb-objc okeychain",
    }

    # Write to XML plist file
    try:
        with open(output_file, "wb") as f:
            plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML)
        print(f"Extracted {len(all_items)} keychain item(s) to {output_file}")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
    except Exception as e:
        result.SetError(f"Failed to write plist file: {e}")


def okeychain_main(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Main entry point for okeychain command.

    Usage:
        okeychain list [--filter=<query>] [--verbose]
        okeychain extract <output_file> [--filter=<query>] [--verbose]
    """
    args = command.strip().split()

    if not args or args[0] == "list":
        # Remove 'list' from command if present
        if args and args[0] == "list":
            command = command.replace("list", "", 1).strip()
        list_keychain_items(debugger, command, result, internal_dict)
    elif args[0] == "extract":
        # Remove 'extract' from command if present
        command = command.replace("extract", "", 1).strip()
        extract_keychain_items(debugger, command, result, internal_dict)
    else:
        result.SetError(
            f"Unknown subcommand: {args[0]}\n\n"
            "Usage:\n"
            "  okeychain list [--filter=<query>] [--verbose]\n"
            "  okeychain extract <output_file> [--filter=<query>] [--verbose]"
        )


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.okeychain_main"
    debugger.HandleCommand(
        f'command script add -h "Query keychain items accessible to the process" -f {module_path} okeychain'
    )
    print(f"[lldb-objc v{__version__}] 'okeychain' installed - Query keychain items")
