#!/usr/bin/env python3
"""
LLDB script for extracting and displaying process entitlements.

Usage:
    oentitlements              # Show entitlements for current process
    oentitlements --xml        # Show raw XML format
    oentitlements --verbose    # Show detailed debug info
"""

from __future__ import annotations

import lldb
import os
import sys
import json
import plistlib
from typing import Any, Dict, Optional, Tuple

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


def _extract_entitlements_csops(
    frame: lldb.SBFrame, verbose: bool = False
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Extract entitlements using csops system call (preferred method).

    Returns: (entitlements_xml_bytes, error)
    """
    target = frame.GetThread().GetProcess().GetTarget()
    process = frame.GetThread().GetProcess()

    if verbose:
        print("[DEBUG] Using csops approach")

    # Get the current process ID
    pid = process.GetProcessID()

    if verbose:
        print(f"[DEBUG] Process ID: {pid}")

    # Define the csops operation code for entitlements
    CS_OPS_ENTITLEMENTS_BLOB = 7

    # Allocate a buffer for the entitlements (8KB should be enough for most cases)
    buffer_size = 8192

    # Expression to call csops and get entitlements
    # The cs_blob structure has a 8-byte header (magic + length), then the data
    expr = f"""
    struct cs_blob {{
        uint32_t magic;
        uint32_t length;
        char data[{buffer_size - 8}];
    }};

    struct cs_blob *buffer = (struct cs_blob *)malloc({buffer_size});
    memset(buffer, 0, {buffer_size});

    extern int csops(int pid, unsigned int ops, void *useraddr, size_t usersize);
    int result = csops({pid}, {CS_OPS_ENTITLEMENTS_BLOB}, buffer, {buffer_size});

    buffer;
    """

    if verbose:
        print(f"[DEBUG] Evaluating csops expression...")

    result = target.EvaluateExpression(expr)

    if not result.IsValid():
        return None, "Failed to evaluate csops expression"

    error = result.GetError()
    if error.Fail():
        # Try the fallback approach if csops fails
        if verbose:
            print(f"[DEBUG] csops failed: {error.GetCString()}")
        return None, f"csops failed: {error.GetCString()}"

    buffer_addr = result.GetValueAsUnsigned(0)
    if buffer_addr == 0:
        return None, "Failed to allocate buffer"

    if verbose:
        print(f"[DEBUG] Buffer address: 0x{buffer_addr:x}")

    # Read the length field (at offset 4, after the magic number)
    error_ref = lldb.SBError()
    length_bytes = process.ReadMemory(buffer_addr + 4, 4, error_ref)
    if error_ref.Fail():
        # Free the buffer
        target.EvaluateExpression(f"free((void *)0x{buffer_addr:x})")
        return None, f"Failed to read length: {error_ref.GetCString()}"

    length = int.from_bytes(length_bytes, byteorder='big')

    if verbose:
        print(f"[DEBUG] Entitlements blob length: {length}")

    if length < 8 or length > buffer_size:
        # Free the buffer
        target.EvaluateExpression(f"free((void *)0x{buffer_addr:x})")
        return None, f"Invalid entitlements length: {length}"

    # Read the data portion (starting at offset 8)
    data_size = length - 8
    entitlements_data = process.ReadMemory(buffer_addr + 8, data_size, error_ref)
    if error_ref.Fail():
        # Free the buffer
        target.EvaluateExpression(f"free((void *)0x{buffer_addr:x})")
        return None, f"Failed to read entitlements: {error_ref.GetCString()}"

    # Free the buffer
    target.EvaluateExpression(f"free((void *)0x{buffer_addr:x})")

    return entitlements_data, None


def _extract_entitlements_linkedit(
    frame: lldb.SBFrame, verbose: bool = False
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Extract entitlements by parsing __LINKEDIT segment (fallback method).

    Returns: (entitlements_xml_bytes, error)
    """
    target = frame.GetThread().GetProcess().GetTarget()
    process = frame.GetThread().GetProcess()

    if verbose:
        print("[DEBUG] Using __LINKEDIT parsing approach")

    # Get the main executable module
    main_module = target.GetModuleAtIndex(0)
    if not main_module.IsValid():
        return None, "No main module found"

    if verbose:
        print(f"[DEBUG] Main module: {main_module.GetFileSpec().GetFilename()}")

    # Find the __LINKEDIT segment
    linkedit_section = None
    for section in main_module.sections:
        if section.GetName() == "__LINKEDIT":
            linkedit_section = section
            break

    if not linkedit_section:
        return None, "__LINKEDIT section not found"

    linkedit_addr = linkedit_section.GetLoadAddress(target)
    linkedit_size = linkedit_section.GetByteSize()

    if verbose:
        print(f"[DEBUG] __LINKEDIT at 0x{linkedit_addr:x}, size: {linkedit_size}")

    # Read the __LINKEDIT segment
    error_ref = lldb.SBError()
    linkedit_data = process.ReadMemory(linkedit_addr, linkedit_size, error_ref)
    if error_ref.Fail():
        return None, f"Failed to read __LINKEDIT: {error_ref.GetCString()}"

    # Search for the embedded signature magic (0xfade0cc0)
    magic = bytes([0xfa, 0xde, 0x0c, 0xc0])
    offset = linkedit_data.find(magic)

    if offset == -1:
        return None, "Code signature not found in __LINKEDIT"

    if verbose:
        print(f"[DEBUG] Found signature at offset: 0x{offset:x}")

    # Parse the SuperBlob header
    # SuperBlob: magic (4) + length (4) + count (4) + BlobIndex entries
    superblob_length = int.from_bytes(linkedit_data[offset + 4:offset + 8], byteorder='big')
    blob_count = int.from_bytes(linkedit_data[offset + 8:offset + 12], byteorder='big')

    if verbose:
        print(f"[DEBUG] SuperBlob length: {superblob_length}, blob count: {blob_count}")

    # Search for the entitlements blob (type 5 = CSSLOT_ENTITLEMENTS)
    index_offset = offset + 12
    for i in range(blob_count):
        blob_type = int.from_bytes(linkedit_data[index_offset:index_offset + 4], byteorder='big')
        blob_offset = int.from_bytes(linkedit_data[index_offset + 4:index_offset + 8], byteorder='big')

        if blob_type == 5:  # CSSLOT_ENTITLEMENTS
            # Found entitlements blob
            entitlements_offset = offset + blob_offset

            # Read the blob header (magic + length)
            blob_magic = linkedit_data[entitlements_offset:entitlements_offset + 4]
            blob_length = int.from_bytes(
                linkedit_data[entitlements_offset + 4:entitlements_offset + 8],
                byteorder='big'
            )

            if verbose:
                print(f"[DEBUG] Entitlements blob at offset: 0x{entitlements_offset:x}, length: {blob_length}")

            # Extract the XML data (skip the 8-byte header)
            entitlements_data = linkedit_data[entitlements_offset + 8:entitlements_offset + blob_length]

            return entitlements_data, None

        index_offset += 8

    return None, "Entitlements blob not found in code signature"


def extract_entitlements(
    frame: lldb.SBFrame, verbose: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Extract and parse entitlements from the current process.

    Returns: (entitlements_dict, error)
    """
    # Try csops first (cleaner approach)
    entitlements_xml, error = _extract_entitlements_csops(frame, verbose)

    if entitlements_xml is None:
        if verbose:
            print(f"[DEBUG] csops failed: {error}, trying __LINKEDIT parsing")
        # Fall back to __LINKEDIT parsing
        entitlements_xml, error = _extract_entitlements_linkedit(frame, verbose)

    if entitlements_xml is None:
        return None, error

    # Parse the XML plist
    try:
        entitlements = plistlib.loads(entitlements_xml)
        return entitlements, None
    except Exception as e:
        return None, f"Failed to parse entitlements XML: {e}"


def show_entitlements(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Show process entitlements in human-readable format.

    Usage:
        oentitlements              # Show entitlements for current process
        oentitlements --xml        # Show raw XML format
        oentitlements --verbose    # Show detailed debug info
    """
    # Parse flags
    show_xml = "--xml" in command
    verbose = "--verbose" in command or "-v" in command

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Get the current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Extract entitlements
    entitlements, error = extract_entitlements(frame, verbose)

    if error:
        result.SetError(f"Failed to extract entitlements: {error}")
        return

    if entitlements is None:
        result.SetError("No entitlements found")
        return

    # Display the entitlements
    if show_xml:
        # Show raw XML
        xml_data = plistlib.dumps(entitlements, fmt=plistlib.FMT_XML)
        print(xml_data.decode('utf-8'))
    else:
        # Show formatted JSON (more readable than plist)
        print("Process Entitlements:")
        print("=" * 60)
        print(json.dumps(entitlements, indent=2, sort_keys=True))
        print("=" * 60)

        # Highlight keychain-access-groups if present
        if "keychain-access-groups" in entitlements:
            groups = entitlements["keychain-access-groups"]
            print(f"\nKeychain Access Groups ({len(groups)}):")
            for group in groups:
                print(f"  - {group}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.show_entitlements"
    debugger.HandleCommand(
        f'command script add -h "Show process entitlements" -f {module_path} oentitlements'
    )
    print(f"[lldb-objc v{__version__}] 'oentitlements' installed - Show process entitlements")
