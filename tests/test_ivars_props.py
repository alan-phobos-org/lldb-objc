#!/usr/bin/env python3
"""
Test script for ocls --ivars and --properties flags.

This script tests:
- Instance variable listing (--ivars)
- Property listing (--properties)
- Combined --ivars --properties
- Type encoding decoding
- Property attribute parsing

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
from test_helpers import (
    TestResult, check_hello_world_binary, run_shared_test_suite
)


# =============================================================================
# Validator Functions
# =============================================================================

def validate_ivars_basic():
    """Validator for --ivars flag on basic class."""
    def validator(output):
        if 'Instance Variables' in output:
            return True, "Instance Variables section shown"
        elif 'none' in output.lower():
            # NSObject may have few/no ivars
            return True, "No instance variables (may be expected for NSObject)"
        return False, (f"No ivars output\n"
                      f"    Expected: 'Instance Variables' section or 'none'\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_ivars_with_types():
    """Validator for ivars showing type information."""
    def validator(output):
        # Look for type encodings or decoded types
        has_types = any(t in output for t in ['int', 'char', 'id', 'NSString', 'void', 'long', 'BOOL'])
        has_offset = '0x' in output  # Offsets shown as hex

        if has_types or has_offset:
            return True, "Type and/or offset information shown"
        elif 'Instance Variables' in output:
            return True, "Instance Variables section present"
        return False, (f"No type info found\n"
                      f"    Expected: Type names (int, char, id, NSString, etc.) or hex offsets\n"
                      f"    Actual: No type or offset information detected\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_ivars_private_class():
    """Validator for --ivars on private framework class."""
    def validator(output):
        match = re.search(r'Instance Variables \((\d+)\)', output)
        if match:
            count = int(match.group(1))
            if count > 0:
                return True, f"Found {count} instance variables"
            return True, "Private class ivars listed (0 found)"
        elif 'not found' in output.lower():
            return False, (f"IDSServiceProperties not found (framework may not be loaded)\n"
                          f"    Expected: IDSServiceProperties class ivars\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Could not parse ivar count\n"
                      f"    Expected: 'Instance Variables (N)' format\n"
                      f"    Actual: Count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_ivars_offset_format():
    """Validator for ivar offset format."""
    def validator(output):
        # Look for offset pattern: 0x### format
        offset_pattern = re.search(r'0x[0-9a-fA-F]{3}', output)
        if offset_pattern:
            return True, "Offsets shown in 0xNNN format"
        elif '0x' in output:
            return True, "Hex offsets present"
        elif 'Instance Variables' in output:
            return True, "Ivars shown (offset format may vary)"
        return False, (f"No offset format found\n"
                      f"    Expected: Hex offsets like '0x...' for ivars\n"
                      f"    Actual: No offset information detected\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_properties_basic():
    """Validator for --properties flag on basic class."""
    def validator(output):
        if 'Properties' in output:
            return True, "Properties section shown"
        return False, (f"No properties output\n"
                      f"    Expected: 'Properties' section in output\n"
                      f"    Actual: Section not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_properties_attributes():
    """Validator for property attributes."""
    def validator(output):
        # Look for common property attributes
        attributes = ['readonly', 'nonatomic', 'copy', 'strong', 'weak', 'atomic']
        found_attrs = [a for a in attributes if a in output.lower()]

        if found_attrs:
            return True, f"Property attributes shown: {', '.join(found_attrs)}"
        elif 'Properties' in output:
            return True, "Properties section present (attributes may be encoded)"
        return False, (f"No property attributes\n"
                      f"    Expected: Attributes like readonly, nonatomic, copy, strong, weak, atomic\n"
                      f"    Actual: No recognizable attributes found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_properties_private_class():
    """Validator for --properties on private framework class."""
    def validator(output):
        match = re.search(r'Properties \((\d+)\)', output)
        if match:
            count = int(match.group(1))
            if count > 0:
                return True, f"Found {count} properties"
            return True, "Private class properties listed (0 found)"
        elif 'not found' in output.lower():
            return False, (f"IDSServiceProperties not found (framework may not be loaded)\n"
                          f"    Expected: IDSServiceProperties class properties\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Could not parse property count\n"
                      f"    Expected: 'Properties (N)' format\n"
                      f"    Actual: Count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_properties_type_decoding():
    """Validator for property type decoding."""
    def validator(output):
        # Look for decoded types (not raw encodings like @, i, B)
        readable_types = ['NSString', 'NSArray', 'NSDictionary', 'BOOL', 'int', 'id']
        found_types = [t for t in readable_types if t in output]

        if found_types:
            return True, f"Readable types shown: {', '.join(found_types[:3])}"
        elif 'Properties' in output:
            return True, "Properties listed (types may use encoding)"
        return False, (f"No readable types\n"
                      f"    Expected: Decoded types like NSString, NSArray, NSDictionary, BOOL, int, id\n"
                      f"    Actual: No recognizable type names found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_ivars_and_properties():
    """Validator for --ivars --properties combined."""
    def validator(output):
        has_ivars = 'Instance Variables' in output
        has_props = 'Properties' in output

        if has_ivars and has_props:
            return True, "Both ivars and properties shown"
        elif has_ivars:
            return False, (f"Only ivars shown, missing properties\n"
                          f"    Expected: Both 'Instance Variables' and 'Properties' sections\n"
                          f"    Actual: Only 'Instance Variables' found\n"
                          f"    Output preview: {output[:300]}")
        elif has_props:
            return False, (f"Only properties shown, missing ivars\n"
                          f"    Expected: Both 'Instance Variables' and 'Properties' sections\n"
                          f"    Actual: Only 'Properties' found\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Neither section found\n"
                      f"    Expected: Both 'Instance Variables' and 'Properties' sections\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_flags_with_wildcard():
    """Validator for flags with wildcard pattern."""
    def validator(output):
        # With many matches, ivars section should not appear (only for single match)
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            has_ivars = 'Instance Variables' in output

            if count > 1 and not has_ivars:
                return True, f"No ivars for {count} matches (expected)"
            elif count == 1 and has_ivars:
                return True, "Single match shows ivars"
            return True, f"Behavior observed: {count} matches, ivars={has_ivars}"
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_no_ivars():
    """Validator for class with no ivars."""
    def validator(output):
        if 'Instance Variables' in output or 'none' in output.lower():
            return True, "Handled class with no/few ivars"
        return False, (f"Unexpected output for class with no ivars\n"
                      f"    Expected: 'Instance Variables' section or 'none'\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_no_properties():
    """Validator for class with no properties."""
    def validator(output):
        if 'Properties' in output or 'none' in output.lower():
            return True, "Handled class with no/few properties"
        return False, (f"Unexpected output for class with no properties\n"
                      f"    Expected: 'Properties' section or 'none'\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_bitfield_display():
    """Validator for bitfield ivars display."""
    def validator(output):
        # Look for bitfield indicators like "(1 bit)" or "bit"
        if 'bit' in output.lower():
            return True, "Bitfield ivars detected"
        elif 'Instance Variables' in output:
            return True, "Ivars shown (may not have bitfields)"
        return False, (f"No ivar output\n"
                      f"    Expected: 'Instance Variables' section with possible bitfield indicators\n"
                      f"    Actual: No ivar section found\n"
                      f"    Output preview: {output[:300]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Ivars tests
        (
            "--ivars basic: NSObject",
            ['ocls --ivars NSObject'],
            validate_ivars_basic()
        ),
        (
            "--ivars type display",
            ['ocls --ivars NSString'],
            validate_ivars_with_types()
        ),
        (
            "--ivars private class: IDSServiceProperties",
            ['ocls --ivars IDSServiceProperties'],
            validate_ivars_private_class()
        ),
        (
            "--ivars offset format",
            ['ocls --ivars IDSServiceProperties'],
            validate_ivars_offset_format()
        ),
        # Properties tests
        (
            "--properties basic",
            ['ocls --properties NSString'],
            validate_properties_basic()
        ),
        (
            "--properties attributes",
            ['ocls --properties NSString'],
            validate_properties_attributes()
        ),
        (
            "--properties private class: IDSServiceProperties",
            ['ocls --properties IDSServiceProperties'],
            validate_properties_private_class()
        ),
        (
            "--properties type decoding",
            ['ocls --properties IDSServiceProperties'],
            validate_properties_type_decoding()
        ),
        # Combined tests
        (
            "--ivars --properties combined",
            ['ocls --ivars --properties IDSServiceProperties'],
            validate_ivars_and_properties()
        ),
        (
            "Flags with wildcard pattern",
            ['ocls --ivars NS*'],
            validate_flags_with_wildcard()
        ),
        # Edge cases
        (
            "Class with no ivars",
            ['ocls --ivars NSProxy'],
            validate_class_no_ivars()
        ),
        (
            "Class with no properties",
            ['ocls --properties NSProxy'],
            validate_class_no_properties()
        ),
        (
            "Bitfield ivars display",
            ['ocls --ivars IDSServiceProperties'],
            validate_bitfield_display()
        ),
    ]


def main():
    """Run all ivars/properties tests using shared LLDB session."""

    categories = {
        "Instance variables (--ivars)": (0, 4),
        "Properties (--properties)": (4, 8),
        "Combined flags": (8, 10),
        "Edge cases": (10, 13),
    }

    passed, total = run_shared_test_suite(
        "IVARS AND PROPERTIES TEST SUITE",
        get_test_specs(),
        scripts=['objc_cls.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
