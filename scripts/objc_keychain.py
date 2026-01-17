#!/usr/bin/env python3
"""
LLDB script for querying keychain items accessible to the current process.

Usage:
    okeychain list              # List all accessible keychain items
    okeychain list --filter=<query>  # Filter by access group or account
    okeychain list --verbose    # Show detailed debug info
"""

from __future__ import annotations

import lldb
import os
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
            # Get the description of the dictionary
            description = child.GetObjectDescription()
            if description:
                # Parse the dictionary description into a dict
                # This is a simplified approach - the description is like a plist
                items.append({
                    "class": class_value,
                    "description": description,
                    "index": i
                })

    return items, None


def _format_keychain_item(item_dict: Dict[str, str], verbose: bool = False) -> str:
    """
    Format a keychain item for display.

    Extracts key fields like access group (agrp), account (acct), and data.
    """
    desc = item_dict.get("description", "")
    class_value = item_dict.get("class", "unknown")

    # Try to extract common fields from the description
    lines = []
    lines.append(f"Class: {class_value}")

    # Common fields to look for
    fields = ["agrp", "acct", "svce", "labl", "v_Data"]

    for field in fields:
        # Simple pattern matching in the description
        if f"{field} = " in desc:
            # Find the value (this is a simplified parser)
            start = desc.find(f"{field} = ")
            if start != -1:
                start += len(f"{field} = ")
                # Find the end (either semicolon or newline)
                end = desc.find(";", start)
                if end == -1:
                    end = desc.find("\n", start)
                if end == -1:
                    end = len(desc)

                value = desc[start:end].strip()

                # Clean up quotes
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]

                # For v_Data, show first 32 chars if it's a string
                if field == "v_Data" and len(value) > 64:
                    value = value[:64] + "..."

                lines.append(f"  {field}: {value}")

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
            desc = item.get("description", "")
            if filter_query.lower() in desc.lower():
                filtered_items.append(item)
        all_items = filtered_items

        if not all_items:
            print(f"No keychain items matching filter: {filter_query}")
            result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
            return

    # Display the items
    print(f"Found {len(all_items)} keychain item(s)")
    print("=" * 60)

    for i, item in enumerate(all_items):
        print(f"\nItem {i + 1}:")
        print("-" * 60)
        if verbose:
            # Show raw description in verbose mode
            print(item.get("description", ""))
        else:
            # Show formatted output
            print(_format_keychain_item(item, verbose))

    print("=" * 60)

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


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
    """
    args = command.strip().split()

    if not args or args[0] == "list":
        # Remove 'list' from command if present
        if args and args[0] == "list":
            command = command.replace("list", "", 1).strip()
        list_keychain_items(debugger, command, result, internal_dict)
    else:
        result.SetError(
            f"Unknown subcommand: {args[0]}\n\n"
            "Usage: okeychain list [--filter=<query>] [--verbose]"
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
