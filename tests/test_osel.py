#!/usr/bin/env python3
"""
Test script for the osel command (Objective-C Selector Finder).

This script tests the osel basic functionality:
- Listing all selectors in a class
- Pattern matching (substring, wildcards)
- Instance vs class method distinction
- Private class support
- Error handling

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

def validate_list_all_methods():
    """Validator for listing all methods in a class."""
    def validator(output):
        if 'Instance methods' in output and 'Class methods' in output:
            total_match = re.search(r'Total: (\d+)', output)
            if total_match:
                count = int(total_match.group(1))
                if count > 10:
                    return True, f"Found {count} methods"
                return False, (f"Expected >10 methods, got {count}\n"
                              f"    Expected: More than 10 total methods for NSString\n"
                              f"    Actual: Found only {count} methods\n"
                              f"    Possible cause: Method enumeration incomplete\n"
                              f"    Output preview: {output[:250]}")
            return True, "Method lists shown"
        return False, (f"Method listing failed\n"
                      f"    Expected: 'Instance methods' and 'Class methods' sections\n"
                      f"    Actual: Missing one or both sections\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_instance_method_prefix():
    """Validator for instance method - prefix."""
    def validator(output):
        if 'Instance methods' in output:
            lines = output.split('\n')
            in_instance_section = False
            for line in lines:
                if 'Instance methods' in line:
                    in_instance_section = True
                elif 'Class methods' in line:
                    in_instance_section = False
                elif in_instance_section and line.strip().startswith('-'):
                    return True, "Instance methods have - prefix"
            return False, (f"No - prefix found on instance methods\n"
                          f"    Expected: Instance methods with '-' prefix\n"
                          f"    Actual: 'Instance methods' section exists but no '-' prefixed methods\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"No instance methods section\n"
                      f"    Expected: 'Instance methods' section in output\n"
                      f"    Actual: Section not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_method_prefix():
    """Validator for class method + prefix."""
    def validator(output):
        if 'Class methods' in output:
            lines = output.split('\n')
            in_class_section = False
            for line in lines:
                if 'Class methods' in line:
                    in_class_section = True
                elif in_class_section and line.strip().startswith('+'):
                    return True, "Class methods have + prefix"
            return True, "Class methods section found (may be empty)"
        return False, (f"No class methods section\n"
                      f"    Expected: 'Class methods' section in output\n"
                      f"    Actual: Section not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_pointer():
    """Validator for class pointer display."""
    def validator(output):
        if 'Class pointer:' in output or '0x' in output:
            return True, "Class pointer shown"
        return False, (f"No class pointer shown\n"
                      f"    Expected: 'Class pointer:' or hex address '0x...'\n"
                      f"    Actual: Neither found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_substring_pattern():
    """Validator for substring pattern matching."""
    def validator(output):
        if 'init' in output.lower():
            init_count = len(re.findall(r'init', output, re.IGNORECASE))
            if init_count > 0:
                return True, f"Found {init_count} init-related matches"
            return False, (f"Pattern 'init' not found in results\n"
                          f"    Expected: Methods containing 'init'\n"
                          f"    Actual: 'init' in output but not in results\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"No matches for 'init'\n"
                      f"    Expected: Methods containing 'init' substring\n"
                      f"    Actual: No 'init' found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_wildcard_pattern():
    """Validator for wildcard pattern matching."""
    def validator(output):
        if 'WithString' in output:
            return True, "Wildcard prefix/suffix matching works"
        elif 'No' in output and 'found' in output:
            return True, "Pattern matching works (no matches for this pattern)"
        return False, (f"Unexpected output for wildcard pattern\n"
                      f"    Expected: Methods containing 'WithString' or 'No...found' message\n"
                      f"    Actual: Neither found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_single_char_wildcard():
    """Validator for single character wildcard."""
    def validator(output):
        if 'Total:' in output:
            return True, "Single-char wildcard handled"
        return False, (f"Unexpected output for single-char wildcard\n"
                      f"    Expected: 'Total:' count in output\n"
                      f"    Actual: Total count not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_case_insensitive():
    """Validator for case-insensitive pattern matching."""
    def validator(output):
        if 'init' in output.lower() and 'Total:' in output:
            return True, "Case-insensitive matching works"
        elif 'No' in output and 'found' in output:
            return False, (f"Case-insensitive matching failed\n"
                          f"    Expected: Methods matching 'INIT' (case-insensitive)\n"
                          f"    Actual: No matches found\n"
                          f"    Possible cause: Pattern matching is case-sensitive\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for case-insensitive test\n"
                      f"    Expected: 'init' methods with 'Total:' count\n"
                      f"    Actual: Unexpected format\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_private_class():
    """Validator for private framework class."""
    def validator(output):
        if 'Instance methods' in output or 'Class methods' in output:
            return True, "Private class methods discovered"
        elif 'not found' in output.lower():
            return False, (f"IDSService not found (framework may not be loaded)\n"
                          f"    Expected: Method sections for IDSService\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for private class\n"
                      f"    Expected: 'Instance methods' or 'Class methods' sections\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_private_class_pattern():
    """Validator for pattern matching on private class."""
    def validator(output):
        if 'service' in output.lower() or 'Total:' in output:
            return True, "Private class pattern matching works"
        elif 'not found' in output.lower():
            return False, (f"IDSService not found\n"
                          f"    Expected: Methods matching 'service' pattern\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output for private class pattern\n"
                      f"    Expected: Methods containing 'service' or 'Total:' count\n"
                      f"    Actual: Neither found\n"
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


def validate_no_class():
    """Validator for missing class argument."""
    def validator(output):
        if 'usage' in output.lower() or 'error' in output.lower():
            return True, "Properly reports usage error"
        return False, (f"Should show usage error\n"
                      f"    Expected: 'usage' or 'error' message\n"
                      f"    Actual: No usage/error message found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_root_class():
    """Validator for root class NSObject."""
    def validator(output):
        if 'Instance methods' in output:
            if 'init' in output or 'description' in output or 'class' in output:
                return True, "Root class methods listed"
            return False, (f"Common methods not found\n"
                          f"    Expected: Common methods like 'init', 'description', or 'class'\n"
                          f"    Actual: Instance methods section exists but common methods missing\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"NSObject listing failed\n"
                      f"    Expected: 'Instance methods' section\n"
                      f"    Actual: Section not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_minimal_class():
    """Validator for minimal class NSProxy."""
    def validator(output):
        if 'Instance methods' in output or 'Class methods' in output or 'Total:' in output:
            return True, "Minimal class handled"
        return False, (f"Unexpected output for minimal class\n"
                      f"    Expected: Method sections or 'Total:' count\n"
                      f"    Actual: None found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_sorted_output():
    """Validator for sorted method output."""
    def validator(output):
        lines = output.split('\n')
        in_instance_section = False
        methods = []

        for line in lines:
            if 'Instance methods' in line:
                in_instance_section = True
            elif 'Class methods' in line:
                break
            elif in_instance_section and line.strip().startswith('-'):
                method_name = line.strip()[1:]  # Remove - prefix
                methods.append(method_name)

        if len(methods) >= 2:
            is_sorted = methods == sorted(methods)
            if is_sorted:
                return True, "Methods are sorted alphabetically"
            return False, (f"Methods are not sorted\n"
                          f"    Expected: Methods in alphabetical order\n"
                          f"    Actual: Methods not sorted\n"
                          f"    First few methods: {methods[:5]}\n"
                          f"    Output preview: {output[:250]}")
        return True, "Not enough methods to verify sorting"
    return validator


def validate_multipart_selector():
    """Validator for multi-part selector display."""
    def validator(output):
        if ':' in output and ('Instance methods' in output or 'Total:' in output):
            return True, "Multi-part selectors displayed"
        return False, (f"No multi-part selectors found\n"
                      f"    Expected: Method names containing ':' with method sections\n"
                      f"    Actual: No ':' found in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_selector_address():
    """Validator for selector address display."""
    def validator(output):
        if 'description' in output:
            has_address = bool(re.search(r'0x[0-9a-fA-F]+', output))
            if has_address:
                return True, "Selector addresses shown"
            return False, (f"No hex addresses found in output\n"
                          f"    Expected: Hex addresses like '0x...' with method names\n"
                          f"    Actual: 'description' found but no addresses\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"No 'description' method found\n"
                      f"    Expected: 'description' method in output\n"
                      f"    Actual: Method not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_selector_address_format():
    """Validator for selector address format."""
    def validator(output):
        lines = output.split('\n')
        for line in lines:
            if line.strip().startswith('-') or line.strip().startswith('+'):
                if re.search(r'0x[0-9a-fA-F]+', line):
                    return True, "Method name and address on same line"
        return False, (f"Address not found on method line\n"
                      f"    Expected: Method lines (starting with '-' or '+') containing hex addresses\n"
                      f"    Actual: No addresses found on method lines\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_instance_only_flag():
    """Validator for --instance flag."""
    def validator(output):
        has_instance = 'Instance methods' in output
        has_class = 'Class methods' in output

        if has_instance and not has_class:
            return True, "--instance flag shows only instance methods"
        elif 'No instance methods found' in output:
            return True, "--instance flag works (no instance methods)"
        return False, (f"Expected only instance methods\n"
                      f"    Expected: 'Instance methods' section only\n"
                      f"    Actual: Has instance={has_instance}, Has class={has_class}\n"
                      f"    Possible cause: --instance flag not filtering correctly\n"
                      f"    Output preview: {output[:250]}")
    return validator


def validate_class_only_flag():
    """Validator for --class flag."""
    def validator(output):
        has_instance = 'Instance methods' in output
        has_class = 'Class methods' in output

        if has_class and not has_instance:
            return True, "--class flag shows only class methods"
        elif 'No class methods found' in output:
            return True, "--class flag works (no class methods)"
        return False, (f"Expected only class methods\n"
                      f"    Expected: 'Class methods' section only\n"
                      f"    Actual: Has instance={has_instance}, Has class={has_class}\n"
                      f"    Possible cause: --class flag not filtering correctly\n"
                      f"    Output preview: {output[:250]}")
    return validator


def validate_instance_flag_with_pattern():
    """Validator for --instance flag with pattern."""
    def validator(output):
        has_instance = 'Instance methods' in output or '-init' in output
        has_class = 'Class methods' in output

        if has_instance and not has_class:
            return True, "--instance with pattern works"
        elif 'No instance methods found' in output:
            return True, "--instance with pattern works (no matches)"
        return False, (f"Unexpected output for --instance with pattern\n"
                      f"    Expected: Instance methods only, no class methods\n"
                      f"    Actual: Has instance={has_instance}, Has class={has_class}\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_flag_with_pattern():
    """Validator for --class flag with pattern."""
    def validator(output):
        has_instance = 'Instance methods' in output
        has_class = 'Class methods' in output or '+' in output

        if has_class and not has_instance:
            return True, "--class with pattern works"
        elif 'No class methods found' in output:
            return True, "--class with pattern works (no matches)"
        return False, (f"Unexpected output for --class with pattern\n"
                      f"    Expected: Class methods only, no instance methods\n"
                      f"    Actual: Has instance={has_instance}, Has class={has_class}\n"
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
            "List all methods: NSString",
            ['osel NSString'],
            validate_list_all_methods()
        ),
        (
            "Instance method prefix: -",
            ['osel NSString'],
            validate_instance_method_prefix()
        ),
        (
            "Class method prefix: +",
            ['osel NSDate'],
            validate_class_method_prefix()
        ),
        (
            "Class pointer display",
            ['osel NSObject'],
            validate_class_pointer()
        ),
        # Pattern matching
        (
            "Substring pattern: init",
            ['osel NSString init'],
            validate_substring_pattern()
        ),
        (
            "Wildcard pattern: *WithString*",
            ['osel NSString *WithString*'],
            validate_wildcard_pattern()
        ),
        (
            "Wildcard: init?",
            ['osel NSObject init?'],
            validate_single_char_wildcard()
        ),
        (
            "Case-insensitive: INIT",
            ['osel NSString INIT'],
            validate_case_insensitive()
        ),
        # Private class
        (
            "Private class: IDSService",
            ['osel IDSService'],
            validate_private_class()
        ),
        (
            "Private class with pattern: IDSService service",
            ['osel IDSService service'],
            validate_private_class_pattern()
        ),
        # Error handling
        (
            "Error: invalid class",
            ['osel NonExistentClass98765'],
            validate_invalid_class()
        ),
        (
            "Error: no class provided",
            ['osel'],
            validate_no_class()
        ),
        # Edge cases
        (
            "Root class: NSObject",
            ['osel NSObject'],
            validate_root_class()
        ),
        (
            "Minimal class: NSProxy",
            ['osel NSProxy'],
            validate_minimal_class()
        ),
        (
            "Sorted method output",
            ['osel NSString'],
            validate_sorted_output()
        ),
        (
            "Multi-part selector display",
            ['osel NSString *:*'],
            validate_multipart_selector()
        ),
        # Selector address display
        (
            "Selector address display",
            ['osel NSObject description'],
            validate_selector_address()
        ),
        (
            "Selector address format",
            ['osel NSString init'],
            validate_selector_address_format()
        ),
        # Method type filter flags
        (
            "Flag: --instance",
            ['osel --instance NSDate'],
            validate_instance_only_flag()
        ),
        (
            "Flag: --class",
            ['osel --class NSDate'],
            validate_class_only_flag()
        ),
        (
            "Flag: --instance with pattern",
            ['osel --instance NSString init*'],
            validate_instance_flag_with_pattern()
        ),
        (
            "Flag: --class with pattern",
            ['osel --class NSDate *date*'],
            validate_class_flag_with_pattern()
        ),
    ]


def main():
    """Run all osel tests using shared LLDB session."""

    categories = {
        "Basic functionality": (0, 4),
        "Pattern matching": (4, 8),
        "Private class": (8, 10),
        "Error handling": (10, 12),
        "Edge cases": (12, 16),
        "Selector address display": (16, 18),
        "Method type filter flags": (18, 22),
    }

    passed, total = run_shared_test_suite(
        "OSEL COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_sel.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
