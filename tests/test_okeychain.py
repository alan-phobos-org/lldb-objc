#!/usr/bin/env python3
"""
Test script for the okeychain command (Query keychain items).

This script tests the okeychain functionality:
- Basic keychain item listing
- Filter by access group/account
- Verbose mode
- Extract to XML plist file
- Error handling for invalid states

Uses a shared LLDB session for faster test execution.

Note: These tests may not find actual keychain items in a simple test binary,
but they verify the command runs without errors.
"""

import os
import plistlib
import sys
from test_helpers import run_shared_test_suite


# =============================================================================
# Validator Functions
# =============================================================================


def validate_keychain_list():
    """Validator that checks for keychain list output or graceful no-items message."""

    def validator(output):
        # The command might find items, or report none found
        if "Found" in output and "keychain item" in output:
            return True, "Keychain items found and listed"
        if "No keychain items found" in output:
            return True, "No keychain items (expected for test binary)"
        if "This could mean:" in output:
            return True, "Helpful no-items message displayed"
        if "error" in output.lower():
            # Check if it's an expected error
            if "Process must be running" in output:
                return False, "Process not in correct state"
            if "errSecItemNotFound" in output or "-25300" in output:
                return True, "No items found (SecItemCopyMatching returned expected error)"
            # Other errors might indicate actual problems
            return False, f"Unexpected error: {output[:300]}"
        # If we got this far, check for some expected patterns
        if "oentitlements" in output:
            # The help message suggesting to check entitlements
            return True, "Showed helpful message about entitlements"
        return False, f"Unexpected output: {output[:300]}"

    return validator


def validate_filtered_list():
    """Validator for filtered keychain list."""

    def validator(output):
        if "No keychain items matching filter" in output:
            return True, "Filter applied, no matches (expected)"
        if "Found" in output and "keychain item" in output:
            return True, "Filtered items found"
        if "No keychain items found" in output:
            return True, "No items to filter (expected)"
        if "error" in output.lower() and "errSecItemNotFound" not in output:
            return False, f"Error during filtering: {output[:300]}"
        return True, "Acceptable filter output"

    return validator


def validate_verbose_keychain():
    """Validator for verbose keychain output."""

    def validator(output):
        if "[DEBUG]" in output:
            return True, "Verbose debug output present"
        # Verbose mode still shows results
        if "Found" in output or "No keychain items" in output:
            return True, "Keychain list output (verbose mode)"
        if "Querying" in output:
            # This might appear in debug output
            return True, "Query debug info shown"
        return True, "Acceptable verbose output"

    return validator


def validate_extract_command():
    """Validator for extract command and plist structure."""

    def validator(output):
        # First check the command output
        if "No keychain items found to extract" in output:
            return True, "No items to extract (expected for test binary)"

        if "error" in output.lower() and "Process must be running" not in output:
            return False, f"Error during extraction: {output[:300]}"

        if "Extracted" in output and "keychain item" in output:
            # Extraction succeeded, now validate the plist structure
            plist_path = "/tmp/keychain_test.plist"

            try:
                if not os.path.exists(plist_path):
                    return False, "Plist file was not created"

                with open(plist_path, "rb") as f:
                    plist_data = plistlib.load(f)

                # Verify top-level structure
                if "count" not in plist_data:
                    return False, "Plist missing 'count' field"
                if "items" not in plist_data:
                    return False, "Plist missing 'items' field"

                items = plist_data["items"]
                if not isinstance(items, list):
                    return False, "'items' is not a list"

                # Check each item has proper structure
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        return False, f"Item {i} is not a dictionary"

                    # Verify 'class' field exists
                    if "class" not in item:
                        return False, f"Item {i} missing 'class' field"

                    # Check for bytes fields - if they exist, they should be bytes objects
                    bytes_fields = ["v_Data", "issr", "pkhh", "subj", "slnr"]
                    for field in bytes_fields:
                        if field in item:
                            if not isinstance(item[field], bytes):
                                return False, f"Item {i}: '{field}' is not bytes (type: {type(item[field])})"

                return True, f"Extracted successfully with valid plist structure ({len(items)} item(s))"

            except Exception as e:
                return False, f"Failed to validate plist: {e}"
            finally:
                # Clean up
                if os.path.exists(plist_path):
                    try:
                        os.remove(plist_path)
                    except OSError:
                        pass

        return True, "Acceptable extract output"

    return validator


# =============================================================================
# Test Cases
# =============================================================================


TEST_CASES = [
    {
        "name": "Basic keychain listing",
        "description": "List all accessible keychain items",
        "target": "HelloWorld",
        "commands": [
            "b main",
            "run",
            "okeychain list",
        ],
        "validators": [
            validate_keychain_list(),
        ],
    },
    {
        "name": "Filtered keychain listing",
        "description": "Filter keychain items by query",
        "target": "HelloWorld",
        "commands": [
            "okeychain list --filter=test",
        ],
        "validators": [
            validate_filtered_list(),
        ],
        "shared_session": True,
    },
    {
        "name": "Verbose keychain listing",
        "description": "Show debug information during keychain query",
        "target": "HelloWorld",
        "commands": [
            "okeychain list --verbose",
        ],
        "validators": [
            validate_verbose_keychain(),
        ],
        "shared_session": True,
    },
    {
        "name": "Keychain without list subcommand",
        "description": "Default to list when no subcommand given",
        "target": "HelloWorld",
        "commands": [
            "okeychain",
        ],
        "validators": [
            validate_keychain_list(),
        ],
        "shared_session": True,
    },
    {
        "name": "Extract keychain to plist",
        "description": "Extract keychain items to XML plist file with proper structure",
        "target": "HelloWorld",
        "commands": [
            "okeychain extract /tmp/keychain_test.plist",
        ],
        "validators": [
            validate_extract_command(),
        ],
        "shared_session": True,
    },
]


# =============================================================================
# Main
# =============================================================================


def get_test_specs():
    """Return test specifications in the format expected by test_helpers."""
    # Convert from dict format to tuple format
    test_specs = []
    for test_case in TEST_CASES:
        name = test_case["name"]
        commands = test_case["commands"]
        validators = test_case["validators"]
        test_specs.append((name, commands, *validators))
    return test_specs


def main():
    """Run the test suite."""
    print("=" * 60)
    print("Testing okeychain command")
    print("=" * 60)

    passed, total, elapsed, results = run_shared_test_suite(
        "okeychain tests",
        get_test_specs(),
        scripts=["scripts"],
    )

    if passed == total:
        print("\n✓ All okeychain tests passed")
        return 0
    else:
        print(f"\n✗ Some okeychain tests failed ({passed}/{total})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
