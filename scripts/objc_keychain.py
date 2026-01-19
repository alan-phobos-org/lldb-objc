#!/usr/bin/env python3
"""
LLDB script for querying keychain items accessible to the current process.

Usage:
    okeychain list              # List all accessible keychain items
    okeychain list --filter=<query>  # Filter by access group or account
    okeychain list --verbose    # Show detailed debug info
    okeychain list --keychain=<path>  # Use specific keychain file
    okeychain extract <file>    # Extract all keychain items to XML plist file
    okeychain extract <file> --filter=<query>  # Extract filtered items
    okeychain extract <file> --raw  # Extract plist and raw data files
    okeychain extract <file> --keychain=<path>  # Use specific keychain file

Note:
    This tool automatically detects and opens process-specific keychain files
    located at /Library/Keychains/<process_name>.keychain (e.g., apsd.keychain).
    For iOS or remote debugging, use --keychain=<path> to manually specify the
    keychain file path (e.g., --keychain=/private/var/Keychains/keychain-2.db).

    It uses SecKeychainOpen and kSecMatchSearchList to access these keychains,
    mirroring how the actual binaries access their own keychain data.

    Keychain authorization prompts are suppressed to prevent SIGSTOP interrupts
    during debugging. Only items accessible without user authentication will be
    returned. This is expected behavior when debugging system processes.

    If no items are found, check the process entitlements with 'oentitlements'
    to verify keychain-access-groups and application-identifier.
"""

from __future__ import annotations

import lldb
import os
import plistlib
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from objc_utils import register_command, require_stopped_process

_initialized = False

# Keychain class constants
KEYCHAIN_CLASSES = {
    "kSecClassGenericPassword": "genp",
    "kSecClassInternetPassword": "inet",
    "kSecClassCertificate": "cert",
    "kSecClassKey": "keys",
    "kSecClassIdentity": "idnt",
}


def _parse_x509_dn(der_bytes: bytes) -> Optional[str]:
    """
    Parse a DER-encoded X.509 Distinguished Name into human-readable format.

    Returns: String like "C=US, O=Apple Inc., CN=Device CA" or None if parsing fails
    """
    if not der_bytes:
        return None

    result = []
    i = 0

    # OID to attribute name mapping
    oid_map = {
        bytes([0x55, 0x04, 0x03]): "CN",  # commonName
        bytes([0x55, 0x04, 0x06]): "C",  # countryName
        bytes([0x55, 0x04, 0x07]): "L",  # localityName
        bytes([0x55, 0x04, 0x08]): "ST",  # stateOrProvinceName
        bytes([0x55, 0x04, 0x0A]): "O",  # organizationName
        bytes([0x55, 0x04, 0x0B]): "OU",  # organizationalUnitName
    }

    try:
        while i < len(der_bytes):
            # Skip SEQUENCE (0x30) and SET (0x31) tags
            if der_bytes[i] in (0x30, 0x31):
                i += 1
                if i >= len(der_bytes):
                    break
                # Skip length byte
                i += 1
                continue

            # Look for OID tag (0x06)
            if der_bytes[i] == 0x06:
                i += 1
                if i >= len(der_bytes):
                    break
                oid_len = der_bytes[i]
                i += 1
                if i + oid_len > len(der_bytes):
                    break
                oid = der_bytes[i : i + oid_len]
                i += oid_len

                # Get attribute name from OID
                attr_name = oid_map.get(oid, f"OID.{oid.hex()}")

                # Next should be the value (various string types)
                if i < len(der_bytes):
                    value_type = der_bytes[i]
                    i += 1
                    if i >= len(der_bytes):
                        break
                    value_len = der_bytes[i]
                    i += 1
                    if i + value_len > len(der_bytes):
                        break
                    value = der_bytes[i : i + value_len]
                    i += value_len

                    # Try to decode the value as UTF-8 or UTF-16BE
                    try:
                        if value_type == 0x1E:  # BMPString (UTF-16BE)
                            value_str = value.decode("utf-16-be")
                        else:
                            value_str = value.decode("utf-8")
                        result.append(f"{attr_name}={value_str}")
                    except UnicodeDecodeError:
                        result.append(f"{attr_name}=<binary>")
            else:
                i += 1

    except (IndexError, ValueError):
        return None

    return ", ".join(result) if result else None


def _parse_certificate_info(cert_bytes: bytes) -> Optional[Dict[str, str]]:
    """
    Parse a DER-encoded X.509 certificate using openssl to extract key information.

    Returns: Dict with 'subject', 'issuer', 'notBefore', 'notAfter', 'serial' or None
    """
    if not cert_bytes:
        return None

    try:
        with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as f:
            f.write(cert_bytes)
            temp_path = f.name

        # Use openssl to parse the certificate
        result = subprocess.run(
            [
                "openssl",
                "x509",
                "-inform",
                "DER",
                "-in",
                temp_path,
                "-noout",
                "-subject",
                "-issuer",
                "-dates",
                "-serial",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        os.unlink(temp_path)

        if result.returncode != 0:
            return None

        # Parse the output into a dictionary
        info = {}
        for line in result.stdout.strip().split("\n"):
            if line.startswith("subject="):
                info["subject"] = line[8:]
            elif line.startswith("issuer="):
                info["issuer"] = line[7:]
            elif line.startswith("notBefore="):
                info["notBefore"] = line[10:]
            elif line.startswith("notAfter="):
                info["notAfter"] = line[9:]
            elif line.startswith("serial="):
                info["serial"] = line[7:]

        return info if info else None

    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        # openssl might not be available or timeout
        return None


def _enhance_certificate_item(item: Dict[str, Any]) -> None:
    """
    Enhance a certificate item with human-readable parsed fields.

    Adds 'issr_readable', 'subj_readable', and 'cert_info' fields in-place.
    Silently handles any parsing errors to avoid breaking the command.
    """
    if item.get("class") != "cert":
        return

    try:
        # Parse issuer (issr)
        if "issr" in item and isinstance(item["issr"], bytes):
            readable_issuer = _parse_x509_dn(item["issr"])
            if readable_issuer:
                item["issr_readable"] = readable_issuer

        # Parse subject (subj)
        if "subj" in item and isinstance(item["subj"], bytes):
            readable_subject = _parse_x509_dn(item["subj"])
            if readable_subject:
                item["subj_readable"] = readable_subject

        # Parse full certificate (v_Data) for detailed info
        if "v_Data" in item and isinstance(item["v_Data"], bytes):
            cert_info = _parse_certificate_info(item["v_Data"])
            if cert_info:
                # Store as formatted string for display
                info_parts = []
                if "subject" in cert_info:
                    info_parts.append(f"Subject: {cert_info['subject']}")
                if "issuer" in cert_info:
                    info_parts.append(f"Issuer: {cert_info['issuer']}")
                if "notBefore" in cert_info and "notAfter" in cert_info:
                    info_parts.append(f"Valid: {cert_info['notBefore']} to {cert_info['notAfter']}")
                if "serial" in cert_info:
                    info_parts.append(f"Serial: {cert_info['serial']}")

                if info_parts:
                    item["cert_info"] = "\n    ".join(info_parts)
    except Exception:
        # Silently ignore any parsing errors - just don't add the parsed fields
        pass


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
    query_{class_value}[(id)kSecUseAuthenticationUI] = (id)kSecUseAuthenticationUISkip;

    CFTypeRef result_{class_value} = NULL;
    OSStatus status_{class_value} = SecItemCopyMatching((CFDictionaryRef)query_{class_value}, &result_{class_value});

    (NSArray *)result_{class_value};
    """

    # Configure expression options to ignore C++ exceptions
    options = lldb.SBExpressionOptions()
    options.SetIgnoreBreakpoints(True)  # Ignore all breakpoints including exception breakpoints
    options.SetTrapExceptions(False)  # Don't trap C++ exceptions

    result = target.EvaluateExpression(expr, options)

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

    # For certificates, show parsed info prominently
    if class_value == "cert":
        # Show readable issuer and subject if available
        if "issr_readable" in item_dict:
            lines.append(f"  Issuer: {item_dict['issr_readable']}")
        if "subj_readable" in item_dict:
            lines.append(f"  Subject: {item_dict['subj_readable']}")

        # Show full certificate info if available
        if "cert_info" in item_dict:
            lines.append("  Certificate:")
            for info_line in item_dict["cert_info"].split("\n"):
                lines.append(f"    {info_line.strip()}")

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

    # Show any other fields not in the common list, excluding internal/parsed fields
    skip_fields = ["issr_readable", "subj_readable", "cert_info"]
    for key, value in item_dict.items():
        if key not in fields and key != "class" and not key.startswith("_") and key not in skip_fields:
            # Skip raw issr/subj if we have readable versions (to avoid duplication)
            if key == "issr" and "issr_readable" in item_dict:
                continue
            if key == "subj" and "subj_readable" in item_dict:
                continue

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
        okeychain list --keychain=<path>  # Use specific keychain file
    """
    # Parse flags
    verbose = "--verbose" in command or "-v" in command
    filter_query = None
    keychain_path = None

    # Extract filter argument
    if "--filter=" in command:
        start = command.find("--filter=") + len("--filter=")
        rest = command[start:].strip()
        # Get the filter value (up to next space or end)
        filter_query = rest.split()[0] if rest else None

    # Extract keychain path argument
    if "--keychain=" in command:
        start = command.find("--keychain=") + len("--keychain=")
        rest = command[start:].strip()
        # Get the keychain path (up to next space or end)
        keychain_path = rest.split()[0] if rest else None

    stopped = require_stopped_process(debugger, result)
    if not stopped:
        return
    frame, process = stopped
    target = debugger.GetSelectedTarget()

    # Get the process name to check for process-specific keychain (if not manually specified)
    process_name = None
    if not keychain_path:
        process_name = target.GetExecutable().GetFilename()
        if verbose:
            print(f"[DEBUG] Process name: {process_name}")
    else:
        if verbose:
            print(f"[DEBUG] Using specified keychain: {keychain_path}")

    # Use the optimized fast query path
    plist_bytes, error = _query_all_keychain_items_fast(target, verbose, process_name, keychain_path)

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

    # Enhance certificate items with parsed fields
    for item in all_items:
        _enhance_certificate_item(item)

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
    target: lldb.SBTarget,
    verbose: bool = False,
    process_name: Optional[str] = None,
    explicit_keychain_path: Optional[str] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Query ALL keychain classes using a single monolithic expression.
    Returns serialized plist data as bytes.

    This is ~100x faster than the old approach:
    - Old: 1400+ expressions for 100 items (14-70 seconds)
    - New: 3 expressions total (<1 second)

    Args:
        target: The LLDB target
        verbose: Enable verbose debug output
        process_name: Name of the process (e.g., 'apsd') to auto-detect process-specific keychain
        explicit_keychain_path: Explicit path to keychain file (overrides auto-detection)

    Returns: (plist_bytes, error)
    """
    if verbose:
        print("[DEBUG] Building monolithic keychain query expression...")

    # Determine keychain path: explicit path takes priority over auto-detection
    keychain_path = None
    if explicit_keychain_path:
        keychain_path = explicit_keychain_path
        if verbose:
            print(f"[DEBUG] Using explicit keychain path: {keychain_path}")
    elif process_name:
        # Check for process-specific keychain in /Library/Keychains/
        potential_path = f"/Library/Keychains/{process_name}.keychain"
        if verbose:
            print(f"[DEBUG] Auto-detecting process-specific keychain: {potential_path}")
        keychain_path = potential_path

    # Build a single expression that queries all classes and serializes to plist
    # Use unique variable names with prefix to avoid symbol conflicts
    # Note: We typedef OSStatus explicitly because LLDB on iOS may not recognize it
    # from @import Security alone
    expr = """
    @import Foundation;
    @import Security;

    // Ensure OSStatus is defined (LLDB on iOS may not pick it up from @import)
    typedef int32_t OSStatus;

    NSMutableArray *lldb_okeychain_all_items = [NSMutableArray array];
    NSMutableArray *lldb_okeychain_search_list = nil;

    """

    # Add code to open process-specific keychain if needed (macOS only)
    # SecKeychainOpen is not available on iOS - iOS uses a single unified keychain
    # accessed via SecItemCopyMatching without needing to specify a keychain file
    if keychain_path:
        # Check if this is iOS by looking at the target triple
        triple = target.GetTriple()
        is_ios = "ios" in triple.lower() or "arm64-apple-darwin" in triple.lower()

        if is_ios:
            if verbose:
                print(f"[DEBUG] iOS detected (triple: {triple}), skipping SecKeychainOpen")
                print("[DEBUG] iOS uses a unified keychain - --keychain option ignored")
        else:
            # Use raw string for path to avoid escaping issues
            expr += f"""
    // Open process-specific keychain (macOS only)
    SecKeychainRef lldb_kc_specific_keychain = NULL;
    OSStatus lldb_kc_open_status = SecKeychainOpen("{keychain_path}", &lldb_kc_specific_keychain);

    if (lldb_kc_open_status == 0 && lldb_kc_specific_keychain != NULL) {{
        lldb_okeychain_search_list = [NSMutableArray arrayWithObject:(__bridge id)lldb_kc_specific_keychain];
    }}

    """

    expr += """
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
        lldb_kc_query[(id)kSecUseAuthenticationUI] = (id)kSecUseAuthenticationUISkip;

        // Use specific keychain search list if available (for process-specific keychains)
        if (lldb_okeychain_search_list != nil) {
            lldb_kc_query[(id)kSecMatchSearchList] = lldb_okeychain_search_list;
        }

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

    # Configure expression options to ignore C++ exceptions
    options = lldb.SBExpressionOptions()
    options.SetIgnoreBreakpoints(True)  # Ignore all breakpoints including exception breakpoints
    options.SetTrapExceptions(False)  # Don't trap C++ exceptions

    result = target.EvaluateExpression(expr, options)

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

    # Check if the NSData pointer is NULL (no items found)
    data_ptr = result.GetValueAsUnsigned()
    if data_ptr == 0:
        if verbose:
            print("[DEBUG] NSData pointer is NULL (no items found)")
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
        okeychain extract <output_file> --raw  # Also extract raw data files
        okeychain extract <output_file> --keychain=<path>  # Use specific keychain file
    """
    # Parse flags
    verbose = "--verbose" in command or "-v" in command
    raw_mode = "--raw" in command
    filter_query = None
    keychain_path = None

    # Extract filter argument
    if "--filter=" in command:
        start = command.find("--filter=") + len("--filter=")
        rest = command[start:].strip()
        filter_query = rest.split()[0] if rest else None
        # Remove filter from command to get the file path
        command = command.replace(f"--filter={filter_query}", "").strip()

    # Extract keychain path argument
    if "--keychain=" in command:
        start = command.find("--keychain=") + len("--keychain=")
        rest = command[start:].strip()
        keychain_path = rest.split()[0] if rest else None
        # Remove keychain from command to get the file path
        command = command.replace(f"--keychain={keychain_path}", "").strip()

    # Remove verbose and raw flags from command
    command = command.replace("--verbose", "").replace("-v", "").replace("--raw", "").strip()

    # Get the output file path
    args = command.strip().split()
    if not args:
        result.SetError(
            "Usage: okeychain extract <output_file> [--filter=<query>] [--verbose] [--raw] [--keychain=<path>]"
        )
        return

    output_file = args[0]

    stopped = require_stopped_process(debugger, result)
    if not stopped:
        return
    frame, process = stopped
    target = debugger.GetSelectedTarget()

    # Get the process name to check for process-specific keychain (if not manually specified)
    process_name = None
    if not keychain_path:
        process_name = target.GetExecutable().GetFilename()
        if verbose:
            print(f"[DEBUG] Process name: {process_name}")
    else:
        if verbose:
            print(f"[DEBUG] Using specified keychain: {keychain_path}")

    # Use the optimized fast query path
    plist_bytes, error = _query_all_keychain_items_fast(target, verbose, process_name, keychain_path)

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

    # Enhance certificate items with parsed fields
    for item in all_items:
        _enhance_certificate_item(item)

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

        # If --raw flag is set, also extract raw data files
        if raw_mode:
            # Create raw directory: remove suffix from output_file and add '-raw'
            base_name = output_file
            # Remove common suffixes
            for suffix in [".plist", ".xml", ".txt"]:
                if base_name.endswith(suffix):
                    base_name = base_name[: -len(suffix)]
                    break
            raw_dir = f"{base_name}-raw"

            try:
                os.makedirs(raw_dir, exist_ok=True)
                if verbose:
                    print(f"[DEBUG] Created raw directory: {raw_dir}")

                # Extract raw data for each item
                raw_count = 0
                for i, item in enumerate(all_items):
                    # Get the data field (v_Data for most items)
                    data = item.get("v_Data")
                    if data is None or not isinstance(data, bytes):
                        if verbose:
                            print(f"[DEBUG] Skipping item {i + 1}: no data or data is not bytes")
                        continue

                    # Get the label (labl) field
                    label = item.get("labl", "unknown")
                    if isinstance(label, bytes):
                        # Convert bytes to string if needed
                        try:
                            label = label.decode("utf-8")
                        except UnicodeDecodeError:
                            label = "unknown"

                    # Sanitize label for filename (remove invalid characters)
                    label = str(label).replace("/", "_").replace("\\", "_").replace(":", "_")

                    # Determine file extension based on class
                    class_val = item.get("class", "")
                    if class_val == "cert":
                        ext = ".crt"
                    else:
                        ext = ".bytes"

                    # Create filename: [itemid]_[labl].ext
                    itemid = i + 1  # Use 1-based index as itemid
                    filename = f"{itemid}_{label}{ext}"
                    filepath = os.path.join(raw_dir, filename)

                    # Write the raw data
                    with open(filepath, "wb") as raw_file:
                        raw_file.write(data)

                    raw_count += 1
                    if verbose:
                        print(f"[DEBUG] Wrote {len(data)} bytes to {filepath}")

                print(f"Extracted {raw_count} raw data file(s) to {raw_dir}")
            except Exception as e:
                result.SetError(f"Failed to write raw files: {e}")
                return

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
        okeychain list [--filter=<query>] [--verbose] [--keychain=<path>]
        okeychain extract <output_file> [--filter=<query>] [--verbose] [--raw] [--keychain=<path>]

    Examples:
        # macOS: auto-detect apsd.keychain
        okeychain list

        # iOS: specify keychain path explicitly
        okeychain list --keychain=/private/var/Keychains/keychain-2.db

        # Extract with custom keychain
        okeychain extract /tmp/keys.plist --keychain=/Library/Keychains/System.keychain
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
            "  okeychain list [--filter=<query>] [--verbose] [--keychain=<path>]\n"
            "  okeychain extract <output_file> [--filter=<query>] [--verbose] [--raw] [--keychain=<path>]\n\n"
            "Examples:\n"
            "  okeychain list --keychain=/private/var/Keychains/keychain-2.db  # iOS\n"
            "  okeychain list --keychain=/Library/Keychains/System.keychain    # macOS system\n"
            "  okeychain extract /tmp/keys.plist --verbose                      # Auto-detect"
        )


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    register_command(
        debugger,
        "okeychain",
        "okeychain_main",
        __name__,
        "Query keychain items accessible to the process",
        "Query keychain items",
    )
