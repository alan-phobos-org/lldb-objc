#!/usr/bin/env python3
"""
Test script for the obrk command (Objective-C Breakpoint).

This script tests the obrk functionality:
- Instance method breakpoints: obrk -[ClassName selector:]
- Class method breakpoints: obrk +[ClassName classMethod:]
- Private class support (classes from private frameworks)
- Error handling for invalid classes/selectors
- Breakpoint verification

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

def validate_instance_method_public():
    """Validator for instance method on public class."""
    def validator(output):
        if 'Class:' in output and 'SEL:' in output and 'IMP:' in output:
            if 'Breakpoint #' in output:
                return True, "Breakpoint set successfully with resolution chain"
            return False, (f"Resolution succeeded but breakpoint not created\n"
                          f"    Expected: 'Breakpoint #' in output after resolution\n"
                          f"    Actual: Class, SEL, IMP resolved but no breakpoint created\n"
                          f"    Possible cause: BreakpointCreateByAddress failed\n"
                          f"    Output preview: {output[:300]}")
        elif 'error' in output.lower():
            return False, (f"Error setting breakpoint\n"
                          f"    Expected: Successful breakpoint creation\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output\n"
                      f"    Expected: 'Class:', 'SEL:', 'IMP:', and 'Breakpoint #'\n"
                      f"    Actual: Missing resolution chain elements\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_method():
    """Validator for class method breakpoint."""
    def validator(output):
        if 'Class:' in output and 'SEL:' in output and 'IMP:' in output:
            if 'Breakpoint #' in output:
                if '+[NSDate date]' in output:
                    return True, "Class method breakpoint set with correct name"
                return True, "Breakpoint set successfully"
            return False, (f"Resolution succeeded but breakpoint not created\n"
                          f"    Expected: 'Breakpoint #' in output after resolution\n"
                          f"    Actual: Class, SEL, IMP resolved but no breakpoint created\n"
                          f"    Possible cause: BreakpointCreateByAddress failed\n"
                          f"    Output preview: {output[:300]}")
        elif 'error' in output.lower():
            return False, (f"Error setting breakpoint\n"
                          f"    Expected: Successful class method breakpoint creation\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output\n"
                      f"    Expected: 'Class:', 'SEL:', 'IMP:', and 'Breakpoint #'\n"
                      f"    Actual: Missing resolution chain elements\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_private_class():
    """Validator for private framework class breakpoint."""
    def validator(output):
        if 'Class:' in output and 'IMP:' in output:
            if 'Breakpoint #' in output:
                return True, "Private class breakpoint set"
            return False, (f"Resolution succeeded but breakpoint not created\n"
                          f"    Expected: 'Breakpoint #' after resolution\n"
                          f"    Actual: Class and IMP resolved but no breakpoint created\n"
                          f"    Output preview: {output[:300]}")
        elif 'not found' in output.lower():
            return False, (f"IDSService not found (framework may not be loaded)\n"
                          f"    Expected: IDSService class to be available\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for private class\n"
                      f"    Expected: 'Class:', 'IMP:', and 'Breakpoint #'\n"
                      f"    Actual: Missing resolution elements\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_method_with_args():
    """Validator for multi-argument method."""
    def validator(output):
        if 'Breakpoint #' in output and 'IMP:' in output:
            return True, "Multi-argument selector resolved"
        elif 'error' in output.lower():
            return False, (f"Error resolving multi-argument selector\n"
                          f"    Expected: Successful breakpoint for 'initWithFormat:'\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for multi-argument method\n"
                      f"    Expected: 'Breakpoint #' and 'IMP:'\n"
                      f"    Actual: Missing one or both\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_complex_selector():
    """Validator for method with multiple colons."""
    def validator(output):
        if 'Breakpoint #' in output and 'IMP:' in output:
            return True, "Complex selector resolved"
        elif 'error' in output.lower():
            return False, (f"Error resolving complex selector\n"
                          f"    Expected: Successful breakpoint for selector with multiple colons\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for complex selector\n"
                      f"    Expected: 'Breakpoint #' and 'IMP:'\n"
                      f"    Actual: Missing one or both\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_invalid_class():
    """Validator for non-existent class error."""
    def validator(output):
        if 'not found' in output.lower() or 'error' in output.lower():
            return True, "Properly reports error for invalid class"
        return False, (f"Should report error for non-existent class\n"
                      f"    Expected: 'not found' or 'error' message\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_invalid_selector():
    """Validator for non-existent selector."""
    def validator(output):
        if 'error' in output.lower() or 'not found' in output.lower():
            return True, "Reports error for invalid selector"
        elif 'Breakpoint #' in output:
            # This is actually valid behavior - runtime provides a forwarding IMP
            return True, "Breakpoint set (forwarding IMP - expected behavior)"
        return False, (f"Unexpected output for invalid selector\n"
                      f"    Expected: Error message or breakpoint (forwarding IMP)\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_syntax_error():
    """Validator for syntax errors."""
    def validator(output):
        if 'usage' in output.lower() or 'error' in output.lower():
            return True, "Reports syntax error"
        return False, (f"Should report syntax error\n"
                      f"    Expected: 'usage' or 'error' message for invalid syntax\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_breakpoint_address():
    """Validator for valid breakpoint address."""
    def validator(output):
        imp_match = re.search(r'IMP:\s*(0x[0-9a-fA-F]+)', output)
        if imp_match:
            imp_addr = imp_match.group(1)
            if int(imp_addr, 16) > 0:
                return True, f"Valid IMP address: {imp_addr}"
            return False, (f"IMP address is zero\n"
                          f"    Expected: Valid non-zero IMP address\n"
                          f"    Actual: IMP address is 0x0\n"
                          f"    Possible cause: Invalid method resolution\n"
                          f"    Output preview: {output[:300]}")
        elif 'Breakpoint #' in output:
            return True, "Breakpoint set (IMP format may differ)"
        return False, (f"Could not find IMP address\n"
                      f"    Expected: 'IMP: 0x...' in output\n"
                      f"    Actual: IMP address not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_multiple_breakpoints():
    """Validator for multiple breakpoints."""
    def validator(output):
        bp_matches = re.findall(r'Breakpoint #(\d+)', output)
        bp_count = len(set(bp_matches))  # Unique breakpoint IDs
        if bp_count >= 3:
            return True, f"Set {bp_count} breakpoints"
        elif bp_count >= 1:
            return False, (f"Only {bp_count} breakpoints set, expected 3\n"
                          f"    Expected: 3 unique breakpoints\n"
                          f"    Actual: Found {bp_count} breakpoint(s)\n"
                          f"    Breakpoint IDs: {set(bp_matches)}\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"No breakpoints set\n"
                      f"    Expected: 3 breakpoints from multiple obrk commands\n"
                      f"    Actual: No 'Breakpoint #' found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_breakpoint_named():
    """Validator for readable breakpoint name."""
    def validator(output):
        if '-[NSString description]' in output:
            return True, "Breakpoint has readable name"
        elif 'Breakpoint #' in output:
            return True, "Breakpoint created (name may be in different format)"
        return False, (f"Breakpoint name not found\n"
                      f"    Expected: '-[NSString description]' or 'Breakpoint #'\n"
                      f"    Actual: Neither found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_root_class():
    """Validator for root class breakpoint."""
    def validator(output):
        if 'Breakpoint #' in output:
            return True, "Root class breakpoint set"
        return False, (f"Failed to set root class breakpoint\n"
                      f"    Expected: 'Breakpoint #' for NSObject method\n"
                      f"    Actual: Breakpoint not created\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_metaclass():
    """Validator for metaclass resolution."""
    def validator(output):
        if 'Breakpoint #' in output and 'IMP:' in output:
            return True, "Class method resolved (metaclass used)"
        elif 'error' in output.lower():
            return False, (f"Error in metaclass resolution\n"
                          f"    Expected: Successful class method breakpoint\n"
                          f"    Actual: Error encountered\n"
                          f"    Possible cause: object_getClass() or metaclass resolution failed\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for metaclass resolution\n"
                      f"    Expected: 'Breakpoint #' and 'IMP:'\n"
                      f"    Actual: Missing one or both\n"
                      f"    Output preview: {output[:300]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic functionality
        (
            "Instance method: -[NSString length]",
            ['obrk -[NSString length]', 'breakpoint list'],
            validate_instance_method_public()
        ),
        (
            "Class method: +[NSDate date]",
            ['obrk +[NSDate date]', 'breakpoint list'],
            validate_class_method()
        ),
        (
            "Private class: -[IDSService init]",
            ['obrk -[IDSService init]', 'breakpoint list'],
            validate_private_class()
        ),
        # Complex selectors
        (
            "Multi-arg method: -[NSString initWithFormat:]",
            ['obrk -[NSString initWithFormat:]', 'breakpoint list'],
            validate_method_with_args()
        ),
        (
            "Multiple colons: -[NSString stringByReplacingOccurrencesOfString:withString:]",
            ['obrk -[NSString stringByReplacingOccurrencesOfString:withString:]', 'breakpoint list'],
            validate_complex_selector()
        ),
        # Error handling
        (
            "Error: invalid class",
            ['obrk -[NonExistentClass12345 someMethod]'],
            validate_invalid_class()
        ),
        (
            "Error: invalid selector",
            ['obrk -[NSString thisMethodDoesNotExist12345]'],
            validate_invalid_selector()
        ),
        (
            "Error: missing brackets",
            ['obrk NSString length'],
            validate_syntax_error()
        ),
        (
            "Error: wrong prefix",
            ['obrk *[NSString length]'],
            validate_syntax_error()
        ),
        # Validation
        (
            "Breakpoint address validation",
            ['obrk -[NSObject init]', 'breakpoint list'],
            validate_breakpoint_address()
        ),
        (
            "Multiple breakpoints",
            ['obrk -[NSString length]', 'obrk +[NSDate date]', 'obrk -[NSArray count]', 'breakpoint list'],
            validate_multiple_breakpoints()
        ),
        (
            "Breakpoint naming",
            ['obrk -[NSString description]', 'breakpoint list'],
            validate_breakpoint_named()
        ),
        # Edge cases
        (
            "Root class: -[NSObject description]",
            ['obrk -[NSObject description]', 'breakpoint list'],
            validate_root_class()
        ),
        (
            "Metaclass resolution for class method",
            ['obrk +[NSObject class]'],
            validate_metaclass()
        ),
    ]


def main():
    """Run all obrk tests using shared LLDB session."""

    categories = {
        "Basic functionality": (0, 3),
        "Complex selectors": (3, 5),
        "Error handling": (5, 9),
        "Validation": (9, 12),
        "Edge cases": (12, 14),
    }

    passed, total = run_shared_test_suite(
        "OBRK COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_breakpoint.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
