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
from datetime import datetime
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
        if verbose:
            print("[DEBUG] NSData value is invalid")
        return None

    data_ptr = nsdata_value.GetValueAsUnsigned()
    if data_ptr == 0:
        if verbose:
            print("[DEBUG] NSData pointer is NULL")
        return None

    # Get the bytes pointer and length
    expr = f"""
    @import Foundation;
    NSData *data_obj = (NSData *){data_ptr};
    (void *)[data_obj bytes];
    """

    bytes_result = target.EvaluateExpression(expr)
    if not bytes_result.IsValid():
        if verbose:
            print("[DEBUG] Failed to get bytes pointer: result invalid")
        return None

    if bytes_result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to get bytes pointer: {bytes_result.GetError().GetCString()}")
        return None

    bytes_ptr = bytes_result.GetValueAsUnsigned()

    # Get length
    expr_len = f"""
    @import Foundation;
    NSData *data_obj = (NSData *){data_ptr};
    (unsigned long)[data_obj length];
    """

    len_result = target.EvaluateExpression(expr_len)
    if not len_result.IsValid():
        if verbose:
            print("[DEBUG] Failed to get data length: result invalid")
        return None

    if len_result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to get data length: {len_result.GetError().GetCString()}")
        return None

    data_length = len_result.GetValueAsUnsigned()

    if verbose:
        print(f"[DEBUG] NSData has length {data_length}, bytes pointer {hex(bytes_ptr) if bytes_ptr else 'NULL'}")

    if data_length == 0:
        return b""

    if bytes_ptr == 0:
        if verbose:
            print("[DEBUG] Bytes pointer is NULL for non-empty NSData")
        return None

    # Limit data size to avoid memory issues
    max_size = 1024 * 1024  # 1MB limit
    if data_length > max_size:
        if verbose:
            print(f"[DEBUG] NSData size {data_length} exceeds maximum {max_size}, truncating")
        data_length = max_size

    # Read the raw bytes from memory
    process = target.GetProcess()
    error = lldb.SBError()
    data = process.ReadMemory(bytes_ptr, data_length, error)

    if error.Fail():
        if verbose:
            print(f"[DEBUG] Failed to read memory: {error.GetCString()}")
        return None

    if verbose:
        print(f"[DEBUG] Successfully read {len(data)} bytes from memory")

    return data


def _extract_nsdate_timestamp(
    target: lldb.SBTarget, nsdate_value: lldb.SBValue, verbose: bool = False
) -> Optional[float]:
    """
    Extract timestamp from an NSDate object.

    Returns: Unix timestamp as float or None if extraction fails
    """
    if not nsdate_value.IsValid():
        return None

    # Get the time interval since reference date
    expr = f"""
    @import Foundation;
    NSDate *date_obj = (NSDate *){nsdate_value.GetValueAsUnsigned()};
    (double)[date_obj timeIntervalSince1970];
    """

    result = target.EvaluateExpression(expr)
    if not result.IsValid() or result.GetError().Fail():
        if verbose:
            print(f"[DEBUG] Failed to get timestamp: {result.GetError()}")
        return None

    # Get the timestamp as a double
    try:
        timestamp = float(result.GetValue())
        return timestamp
    except (ValueError, TypeError):
        if verbose:
            print("[DEBUG] Failed to convert timestamp to float")
        return None


def _parse_keychain_dict(
    target: lldb.SBTarget, dict_value: lldb.SBValue, class_value: str, verbose: bool = False
) -> Optional[Dict[str, Any]]:
    """
    DEPRECATED: Use _query_all_keychain_items_fast() instead.

    Parse an NSDictionary from keychain query into a Python dict with proper types.
    This function is extremely slow because it makes 1 expression call per dictionary key.
    For 100 items with 10 keys each = 1000+ expressions = 10-50 seconds!
    Kept for reference only.

    Returns: dictionary with parsed fields or None if parsing fails
    """
    if not dict_value.IsValid():
        if verbose:
            print("[DEBUG] dict_value is invalid")
        return None

    result_dict = {"class": class_value}

    # Get the dictionary pointer value
    dict_ptr = dict_value.GetValueAsUnsigned()
    if dict_ptr == 0:
        if verbose:
            print("[DEBUG] dict_value pointer is NULL")
        return result_dict

    try:
        # Get all keys from the dictionary
        expr = f"""
        @import Foundation;
        NSDictionary *dict = (NSDictionary *){dict_ptr};
        (NSArray *)[dict allKeys];
        """

        keys_result = target.EvaluateExpression(expr)
        if not keys_result.IsValid() or keys_result.GetError().Fail():
            if verbose:
                error_msg = keys_result.GetError().GetCString() if keys_result.IsValid() else "Invalid result"
                print(f"[DEBUG] Failed to get dictionary keys: {error_msg}")
                print(f"[DEBUG] dict_value type: {dict_value.GetTypeName()}")
                print(f"[DEBUG] dict_ptr: {hex(dict_ptr)}")
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
                if verbose:
                    print(f"[DEBUG] Key {i} is invalid")
                continue

            # Get the key as a string
            key_str = key_value.GetSummary()
            if key_str:
                # Remove quotes from the string summary
                key_str = key_str.strip('"')
            else:
                if verbose:
                    print(f"[DEBUG] Key {i} has no summary")
                continue

            # Skip internal/computed keys that aren't real fields
            if key_str in ["description", "debugDescription", "hash", "superclass"]:
                if verbose:
                    print(f"[DEBUG] Skipping computed key: {key_str}")
                continue

            # Escape special characters in the key string
            key_str_escaped = key_str.replace("\\", "\\\\").replace('"', '\\"')

            # Get the value for this key
            expr_val = f"""
            @import Foundation;
            NSDictionary *dict = (NSDictionary *){dict_ptr};
            (id)[dict objectForKey:@"{key_str_escaped}"];
            """

            val_result = target.EvaluateExpression(expr_val)
            if not val_result.IsValid():
                if verbose:
                    print(f"[DEBUG] Failed to get value for key '{key_str}'")
                continue

            if val_result.GetError().Fail():
                if verbose:
                    print(f"[DEBUG] Error getting value for key '{key_str}': {val_result.GetError().GetCString()}")
                continue

            # Determine the type and extract accordingly
            type_name = val_result.GetTypeName()

            if verbose:
                print(f"[DEBUG] Processing key '{key_str}' with type '{type_name}'")

            if (
                "NSData" in type_name
                or "NSCFData" in type_name
                or "NSConcreteData" in type_name
                or "_NSInlineData" in type_name
            ):
                # Extract raw bytes
                data_bytes = _extract_nsdata_bytes(target, val_result, verbose)
                if data_bytes is not None:
                    result_dict[key_str] = data_bytes
                    if verbose:
                        print(f"[DEBUG] Successfully extracted NSData for key '{key_str}' ({len(data_bytes)} bytes)")
                else:
                    if verbose:
                        print(f"[DEBUG] Failed to extract NSData for key '{key_str}', skipping")
            elif (
                "NSString" in type_name
                or "NSCFString" in type_name
                or "__NSCFConstantString" in type_name
                or "NSTaggedPointerString" in type_name
            ):
                # Extract string value
                string_val = val_result.GetSummary()
                if string_val:
                    # Remove quotes
                    string_val = string_val.strip('"')
                    result_dict[key_str] = string_val
                    if verbose:
                        print(f"[DEBUG] Extracted string for key '{key_str}': {string_val[:50]}")
                else:
                    result_dict[key_str] = ""
            elif (
                "NSNumber" in type_name
                or "NSCFNumber" in type_name
                or "__NSCFNumber" in type_name
                or "NSTaggedPointerNumber" in type_name
            ):
                # Extract number value - try as unsigned first
                num_val = val_result.GetValueAsUnsigned()
                result_dict[key_str] = num_val
                if verbose:
                    print(f"[DEBUG] Extracted number for key '{key_str}': {num_val}")
            elif (
                "NSDate" in type_name
                or "NSCFDate" in type_name
                or "__NSDate" in type_name
                or "__NSTaggedDate" in type_name
            ):
                # Extract timestamp from NSDate
                timestamp = _extract_nsdate_timestamp(target, val_result, verbose)
                if timestamp is not None:
                    result_dict[key_str] = timestamp
                    if verbose:
                        print(f"[DEBUG] Extracted timestamp for key '{key_str}': {timestamp}")
                else:
                    if verbose:
                        print(f"[DEBUG] Failed to extract NSDate for key '{key_str}', skipping")
            else:
                # For unknown types, log and skip
                if verbose:
                    print(f"[DEBUG] Skipping unknown type for key '{key_str}': {type_name}")

    except Exception as e:
        if verbose:
            print(f"[DEBUG] Exception during dict parsing: {e}")
        pass

    return result_dict


def _query_keychain_class(
    frame: lldb.SBFrame, class_name: str, class_value: str, verbose: bool = False
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    DEPRECATED: Use _query_all_keychain_items_fast() instead.

    Query a single keychain class for all accessible items.
    This function is slow because it makes O(N*M) expression calls where
    N=items and M=fields per item. Kept for reference only.

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
    fields = ["agrp", "acct", "svce", "labl", "v_Data", "cdat", "mdat"]

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
            elif isinstance(value, float):
                # Format timestamp as readable date
                try:
                    date_str = datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
                    lines.append(f"  {field}: {date_str}")
                except (ValueError, OSError):
                    lines.append(f"  {field}: {value}")
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
            elif isinstance(value, float):
                # Format timestamp as readable date
                try:
                    date_str = datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
                    lines.append(f"  {key}: {date_str}")
                except (ValueError, OSError):
                    lines.append(f"  {key}: {value}")
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

    # Use the optimized fast query path
    plist_bytes, error = _query_all_keychain_items_fast(target, verbose)

    if error:
        result.SetError(error)
        return

    if not plist_bytes:
        print("No keychain items found.")
        print("\nThis could mean:")
        print("  1. The app has no keychain items")
        print("  2. The keychain is locked")
        print("  3. The app lacks necessary entitlements")
        print("\nUse 'oentitlements' to check keychain-access-groups")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Parse the plist data
    try:
        all_items = plistlib.loads(plist_bytes)
        if not isinstance(all_items, list):
            result.SetError("Unexpected plist format: expected array")
            return
    except Exception as e:
        result.SetError(f"Failed to parse plist data: {e}")
        return

    if verbose:
        print(f"[DEBUG] Parsed {len(all_items)} items from plist")

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


def _query_all_keychain_items_fast(
    target: lldb.SBTarget, verbose: bool = False
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Query ALL keychain classes using a single monolithic expression.
    Returns serialized plist data as bytes.

    This is ~100x faster than the old approach:
    - Old: 1400+ expressions for 100 items (14-70 seconds)
    - New: 3 expressions total (<1 second)

    Returns: (plist_bytes, error)
    """
    if verbose:
        print("[DEBUG] Building monolithic keychain query expression...")

    # Build a single expression that queries all classes and serializes to plist
    # Use unique variable names with prefix to avoid symbol conflicts
    expr = """
    @import Foundation;
    @import Security;

    NSMutableArray *lldb_okeychain_all_items = [NSMutableArray array];

    // Query each keychain class
    NSArray *lldb_okeychain_sec_classes = @[
        (id)kSecClassGenericPassword,
        (id)kSecClassInternetPassword,
        (id)kSecClassCertificate,
        (id)kSecClassKey,
        (id)kSecClassIdentity
    ];

    NSArray *lldb_okeychain_class_vals = @[@"genp", @"inet", @"cert", @"keys", @"idnt"];

    for (NSUInteger lldb_kc_idx = 0; lldb_kc_idx < [lldb_okeychain_sec_classes count]; lldb_kc_idx++) {
        id lldb_kc_sec_class = lldb_okeychain_sec_classes[lldb_kc_idx];
        NSString *lldb_kc_class_val = lldb_okeychain_class_vals[lldb_kc_idx];

        NSMutableDictionary *lldb_kc_query = [NSMutableDictionary dictionary];
        lldb_kc_query[(id)kSecClass] = lldb_kc_sec_class;
        lldb_kc_query[(id)kSecReturnAttributes] = @YES;
        lldb_kc_query[(id)kSecReturnData] = @YES;
        lldb_kc_query[(id)kSecMatchLimit] = (id)kSecMatchLimitAll;

        CFTypeRef lldb_kc_query_result = NULL;
        OSStatus lldb_kc_status = SecItemCopyMatching((CFDictionaryRef)lldb_kc_query, &lldb_kc_query_result);

        if (lldb_kc_status == 0 && lldb_kc_query_result != NULL) {
            NSArray *lldb_kc_items = (NSArray *)lldb_kc_query_result;

            // Add class field to each item
            for (NSUInteger lldb_kc_i = 0; lldb_kc_i < [lldb_kc_items count]; lldb_kc_i++) {
                NSDictionary *lldb_kc_item = lldb_kc_items[lldb_kc_i];
                NSMutableDictionary *lldb_kc_item_copy = [lldb_kc_item mutableCopy];
                lldb_kc_item_copy[@"class"] = lldb_kc_class_val;
                [lldb_okeychain_all_items addObject:lldb_kc_item_copy];
            }
        }
    }

    // Serialize to plist (binary format for efficiency)
    NSData *lldb_okeychain_plist_data = nil;
    if ([lldb_okeychain_all_items count] > 0) {
        NSError *lldb_kc_error = nil;
        lldb_okeychain_plist_data = [NSPropertyListSerialization dataWithPropertyList:lldb_okeychain_all_items
                                                                format:NSPropertyListBinaryFormat_v1_0
                                                               options:0
                                                                 error:&lldb_kc_error];
    }

    (NSData *)lldb_okeychain_plist_data;
    """

    if verbose:
        print("[DEBUG] Executing monolithic query...")

    result = target.EvaluateExpression(expr)

    if not result.IsValid():
        if verbose:
            print("[DEBUG] Expression result is invalid")
        return None, "Expression evaluation failed"

    if result.GetError().Fail():
        error_msg = result.GetError().GetCString()
        if verbose:
            print(f"[DEBUG] Expression error: {error_msg}")
        # Check if it's just "no items found"
        if "errSecItemNotFound" in error_msg or "-25300" in error_msg:
            return None, None
        return None, f"Query failed: {error_msg}"

    # Check if we got NSData back
    type_name = result.GetTypeName()
    if not any(x in type_name for x in ["NSData", "NSCFData", "NSConcreteData", "_NSInlineData"]):
        if verbose:
            print(f"[DEBUG] No data returned (type: {type_name})")
        return None, None

    # Extract the plist bytes using the existing helper
    plist_bytes = _extract_nsdata_bytes(target, result, verbose)

    if plist_bytes is None:
        return None, "Failed to extract plist data"

    if verbose:
        print(f"[DEBUG] Successfully extracted {len(plist_bytes)} bytes of plist data")

    return plist_bytes, None


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

    # Use the optimized fast query path
    plist_bytes, error = _query_all_keychain_items_fast(target, verbose)

    if error:
        result.SetError(error)
        return

    if not plist_bytes:
        print("No keychain items found to extract.")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Parse the plist data
    try:
        all_items = plistlib.loads(plist_bytes)
        if not isinstance(all_items, list):
            result.SetError("Unexpected plist format: expected array")
            return
    except Exception as e:
        result.SetError(f"Failed to parse plist data: {e}")
        return

    if verbose:
        print(f"[DEBUG] Parsed {len(all_items)} items from plist")

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

    # Convert items to plist format for export
    plist_items = []
    for i, item in enumerate(all_items):
        # Add an index field to each item
        item_with_index = {"index": i + 1}
        # Copy all fields from the original item, converting timestamps to datetime objects
        for key, value in item.items():
            if isinstance(value, float):
                # Convert Unix timestamp to datetime object for proper plist serialization
                try:
                    item_with_index[key] = datetime.fromtimestamp(value)
                except (ValueError, OSError):
                    # If conversion fails, keep as float
                    item_with_index[key] = value
            elif isinstance(value, str):
                # Check if string contains control characters - if so, convert to bytes
                # This can happen with certain keychain fields
                try:
                    # Try to encode/decode to check for control characters
                    value.encode("utf-8")
                    # Check for control characters (except whitespace)
                    if any(ord(c) < 32 and c not in "\t\n\r" for c in value):
                        # Convert to bytes for plist
                        item_with_index[key] = value.encode("utf-8")
                    else:
                        item_with_index[key] = value
                except (UnicodeDecodeError, UnicodeEncodeError):
                    # If encoding fails, store as bytes
                    item_with_index[key] = value.encode("utf-8", errors="replace")
            else:
                item_with_index[key] = value
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
