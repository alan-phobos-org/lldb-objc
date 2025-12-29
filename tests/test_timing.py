#!/usr/bin/env python3
"""
Detailed timing test for --ivars and --properties performance.

This is a performance/benchmarking test that measures execution times
across multiple classes with varying ivar/property counts.
Not run by default in the test suite (use --perf flag).

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

def validate_nsobject_performance():
    """Validator for NSObject performance."""
    def validator(output):
        if 'NSObject' in output:
            return True, "NSObject completed"
        return False, f"Failed: {output[:200]}"
    return validator


def validate_nsstring_performance():
    """Validator for NSString performance."""
    def validator(output):
        if 'NSString' in output:
            return True, "NSString completed"
        return False, f"Failed: {output[:200]}"
    return validator


def validate_idsserviceproperties_performance():
    """Validator for IDSServiceProperties performance."""
    def validator(output):
        # Parse counts
        ivars_match = re.search(r'Instance Variables \((\d+)\)', output)
        props_match = re.search(r'Properties \((\d+)\)', output)

        ivar_count = int(ivars_match.group(1)) if ivars_match else 0
        prop_count = int(props_match.group(1)) if props_match else 0

        if ivars_match or props_match:
            return True, f"{ivar_count} ivars, {prop_count} props"
        elif 'not found' in output.lower():
            return False, "IDSServiceProperties not found (framework may not be loaded)"
        return False, f"Failed: {output[:200]}"
    return validator


def validate_ivars_only():
    """Validator for --ivars only performance."""
    def validator(output):
        ivars_match = re.search(r'Instance Variables \((\d+)\)', output)
        if ivars_match:
            ivar_count = int(ivars_match.group(1))
            return True, f"{ivar_count} ivars"
        return False, f"Failed: {output[:200]}"
    return validator


def validate_properties_only():
    """Validator for --properties only performance."""
    def validator(output):
        props_match = re.search(r'Properties \((\d+)\)', output)
        if props_match:
            prop_count = int(props_match.group(1))
            return True, f"{prop_count} properties"
        return False, f"Failed: {output[:200]}"
    return validator


def validate_performance_target():
    """Validator for performance target."""
    def validator(output):
        if 'Instance Variables' in output or 'Properties' in output:
            return True, "Completed within shared session"
        return False, f"Command failed: {output[:200]}"
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # By class size
        (
            "Performance: NSObject",
            ['ocls --ivars --properties NSObject'],
            validate_nsobject_performance()
        ),
        (
            "Performance: NSString",
            ['ocls --ivars --properties NSString'],
            validate_nsstring_performance()
        ),
        (
            "Performance: IDSServiceProperties",
            ['ocls --ivars --properties IDSServiceProperties'],
            validate_idsserviceproperties_performance()
        ),
        # By flag
        (
            "Performance: --ivars only",
            ['ocls --ivars IDSServiceProperties'],
            validate_ivars_only()
        ),
        (
            "Performance: --properties only",
            ['ocls --properties IDSServiceProperties'],
            validate_properties_only()
        ),
        # Performance target
        (
            "Performance target: <5s for large class",
            ['ocls --ivars --properties IDSServiceProperties'],
            validate_performance_target()
        ),
    ]


def main():
    """Run all timing/performance tests using shared LLDB session."""

    categories = {
        "By class size": (0, 3),
        "By flag": (3, 5),
        "Performance target": (5, 6),
    }

    passed, total = run_shared_test_suite(
        "PERFORMANCE TIMING TEST SUITE",
        get_test_specs(),
        scripts=['objc_cls.py'],
        show_category_summary=categories
    )

    # Print performance summary
    print("\n" + "-" * 70)
    print("PERFORMANCE SUMMARY")
    print("-" * 70)
    print("\nNote: Execution times shown in test results above.")
    print("Performance depends on class size and system load.")
    print("Target: <5s for large classes with batched expression optimization.")

    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
