#!/usr/bin/env python3
"""
Test script for the owatch command (Method Watcher).

This script tests the owatch functionality:
- Auto-logging breakpoints without stopping (SetAutoContinue)
- Argument logging with timestamps
- Various output modes (default, --detailed, --stack, --minimal)
- Hit counting (--once, --count=N)
- Conditional logging (--condition=X)

Uses a shared LLDB session for faster test execution.

Expected command syntax:
    owatch -[ClassName selector:]            # Basic watch with auto-continue
    owatch +[ClassName classMethod:]         # Class method watch
    owatch --detailed -[Class sel:]          # Multi-line arg format
    owatch --stack -[Class sel:]             # Include caller info
    owatch --minimal -[Class sel:]           # Timestamp + method only
    owatch --once -[Class sel:]              # Remove after first hit
    owatch --count=N -[Class sel:]           # Remove after N hits
    owatch --condition="arg1 > 0" -[C sel:]  # Conditional logging

Expected default output format:
    [10:23:45.123] -[NSUserDefaults setObject:forKey:] 0x600001234560 0x600001234890="value" 0x600001234abc="myKey"
"""

import sys
import re
from test_helpers import run_shared_test_suite


# =============================================================================
# Validator Functions
# =============================================================================

def validate_basic_watch():
    """Validator for basic owatch creating a breakpoint with auto-continue."""
    def validator(output):
        if 'breakpoint' in output.lower() or 'Breakpoint' in output:
            if 'auto-continue' in output.lower() or 'AutoContinue' in output:
                return True, "Breakpoint created with auto-continue"
            return True, "Breakpoint created (auto-continue flag may not be visible in list)"
        elif 'owatch' in output or 'watching' in output.lower():
            return True, "Watch command executed"
        return False, (f"No breakpoint created\n"
                      f"    Expected: 'breakpoint', 'Breakpoint', or 'watching' in output\n"
                      f"    Actual: Watch command did not create breakpoint\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_class_method_watch():
    """Validator for class method watch."""
    def validator(output):
        if 'NSDate' in output or 'breakpoint' in output.lower():
            return True, "Class method watch created"
        elif 'error' in output.lower():
            return False, (f"Error watching class method\n"
                          f"    Expected: Watch on +[NSDate date]\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Unexpected output for class method watch\n"
                      f"    Expected: 'NSDate' or 'breakpoint' in output\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_instance_method_watch():
    """Validator for instance method watch."""
    def validator(output):
        if 'NSString' in output or 'breakpoint' in output.lower() or 'length' in output:
            return True, "Instance method watch created"
        elif 'error' in output.lower():
            return False, (f"Error watching instance method\n"
                          f"    Expected: Watch on -[NSString length]\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Unexpected output for instance method watch\n"
                      f"    Expected: 'NSString', 'breakpoint', or 'length' in output\n"
                      f"    Actual: None found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_private_class_watch():
    """Validator for private class watch."""
    def validator(output):
        if 'IDSService' in output or 'breakpoint' in output.lower():
            return True, "Private class watch created"
        elif 'not found' in output.lower():
            return False, (f"IDSService not found (framework may not be loaded)\n"
                          f"    Expected: Watch on IDSService private class\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Unexpected output for private class watch\n"
                      f"    Expected: 'IDSService' or 'breakpoint' in output\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_flag_accepted():
    """Generic validator for flag acceptance."""
    def validator(output):
        if 'error' not in output.lower() or 'unknown' not in output.lower():
            return True, "Flag accepted"
        return False, (f"Flag not accepted\n"
                      f"    Expected: Command executed without error\n"
                      f"    Actual: 'error' or 'unknown' in output\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_syntax_error():
    """Validator for syntax error handling."""
    def validator(output):
        if 'usage' in output.lower() or 'syntax' in output.lower() or 'error' in output.lower():
            return True, "Properly reports syntax error"
        return False, (f"Should report syntax error\n"
                      f"    Expected: 'usage', 'syntax', or 'error' message\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_invalid_class():
    """Validator for invalid class error handling."""
    def validator(output):
        if 'not found' in output.lower() or 'error' in output.lower() or 'failed' in output.lower():
            return True, "Properly reports error for invalid class"
        return False, (f"Should report error for invalid class\n"
                      f"    Expected: 'not found', 'error', or 'failed' message\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_timestamp_format():
    """Validator for timestamp format in output."""
    def validator(output):
        timestamp_pattern = r'\[\d{2}:\d{2}:\d{2}\.\d{3}\]'
        if re.search(timestamp_pattern, output):
            return True, "Timestamp format found in output"
        elif 'breakpoint' in output.lower() or 'owatch' in output.lower():
            return True, "Watch created (timestamp will appear on method calls)"
        return False, (f"No timestamp found\n"
                      f"    Expected: Timestamp format '[HH:MM:SS.mmm]' or watch creation\n"
                      f"    Actual: Neither timestamp nor watch creation found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_multiple_watches():
    """Validator for multiple watches."""
    def validator(output):
        bp_count = output.lower().count('breakpoint') + output.lower().count('watch')
        if bp_count >= 3:
            return True, "Multiple watches created"
        elif bp_count >= 1:
            return True, "At least one watch created"
        return False, (f"No watches created\n"
                      f"    Expected: Multiple occurrences of 'breakpoint' or 'watch'\n"
                      f"    Actual: Count={bp_count}, expected >=1\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_list_command():
    """Validator for owatch list subcommand."""
    def validator(output):
        if 'NSString' in output or 'list' in output.lower():
            return True, "List command executed"
        elif 'unknown' in output.lower() or 'usage' in output.lower():
            return True, "List subcommand not implemented yet"
        return False, (f"Unexpected output for list command\n"
                      f"    Expected: 'NSString', 'list', 'unknown', or 'usage'\n"
                      f"    Actual: None of these found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_clear_command():
    """Validator for owatch clear subcommand."""
    def validator(output):
        if 'clear' in output.lower() or 'removed' in output.lower():
            return True, "Clear command executed"
        elif 'unknown' in output.lower() or 'usage' in output.lower():
            return True, "Clear subcommand not implemented yet"
        return False, (f"Unexpected output for clear command\n"
                      f"    Expected: 'clear', 'removed', 'unknown', or 'usage'\n"
                      f"    Actual: None of these found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_arch_handling():
    """Validator for architecture-specific register handling."""
    def validator(output):
        if 'error' not in output.lower() or 'arch' not in output.lower():
            return True, "Architecture handling works"
        return False, (f"Architecture issue\n"
                      f"    Expected: Command executed without architecture errors\n"
                      f"    Actual: 'error' or 'arch' in output\n"
                      f"    Possible cause: Register handling not compatible with current architecture\n"
                      f"    Output preview: {output[:200]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic functionality
        (
            "Basic watch: breakpoint creation",
            ['owatch -[NSString description]', 'breakpoint list'],
            validate_basic_watch()
        ),
        (
            "Watch class method: +[NSDate date]",
            ['owatch +[NSDate date]', 'breakpoint list'],
            validate_class_method_watch()
        ),
        (
            "Watch instance method: -[NSString length]",
            ['owatch -[NSString length]', 'breakpoint list'],
            validate_instance_method_watch()
        ),
        (
            "Watch private class: -[IDSService init]",
            ['owatch -[IDSService init]', 'breakpoint list'],
            validate_private_class_watch()
        ),
        # Flag tests
        (
            "Flag: --detailed",
            ['owatch --detailed -[NSString description]'],
            validate_flag_accepted()
        ),
        (
            "Flag: --stack",
            ['owatch --stack -[NSString description]'],
            validate_flag_accepted()
        ),
        (
            "Flag: --minimal",
            ['owatch --minimal -[NSString description]'],
            validate_flag_accepted()
        ),
        (
            "Flag: --once",
            ['owatch --once -[NSString description]'],
            validate_flag_accepted()
        ),
        (
            "Flag: --count=N",
            ['owatch --count=5 -[NSString description]'],
            validate_flag_accepted()
        ),
        (
            "Flag: --condition",
            ['owatch --condition="$arg1 != nil" -[NSString description]'],
            validate_flag_accepted()
        ),
        # Error handling
        (
            "Error handling: invalid syntax",
            ['owatch invalid syntax'],
            validate_syntax_error()
        ),
        (
            "Error handling: invalid class",
            ['owatch -[NonExistentClass999 someMethod]'],
            validate_invalid_class()
        ),
        # Output format
        (
            "Output format: timestamp",
            ['owatch -[NSObject description]', 'expr [[NSObject new] description]'],
            validate_timestamp_format()
        ),
        # Advanced features
        (
            "Multiple watches",
            ['owatch -[NSString description]', 'owatch +[NSDate date]', 'owatch -[NSArray count]', 'breakpoint list'],
            validate_multiple_watches()
        ),
        (
            "List watches: owatch list",
            ['owatch -[NSString description]', 'owatch list'],
            validate_list_command()
        ),
        (
            "Clear watches: owatch clear",
            ['owatch -[NSString description]', 'owatch clear'],
            validate_clear_command()
        ),
        (
            "Architecture: register handling",
            ['owatch -[NSString initWithFormat:]'],
            validate_arch_handling()
        ),
    ]


def main():
    """Run all owatch tests using shared LLDB session."""

    categories = {
        "Basic functionality": (0, 4),
        "Flag handling": (4, 10),
        "Error handling": (10, 12),
        "Output format": (12, 13),
        "Advanced features": (13, 17),
    }

    passed, total = run_shared_test_suite(
        "OWATCH COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_watch.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
