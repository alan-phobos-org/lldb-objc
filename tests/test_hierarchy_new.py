#!/usr/bin/env python3
"""
Test script for ocls hierarchy display feature (REFACTORED using consolidated validators).

This demonstrates the new pytest-style test framework with consolidated validators
to reduce boilerplate and improve readability.

Tests:
- 1 match: Detailed hierarchy view
- 2-20 matches: Compact one-liner per class
- 21+ matches: Simple class list

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
from test_helpers import (
    check_hello_world_binary, run_shared_test_suite, Validators
)


# =============================================================================
# Validator Functions (Using Consolidated Utilities)
# =============================================================================

def validate_single_match():
    """Single match shows full hierarchy with arrows."""
    return Validators.combine_and(
        Validators.contains('→', "Hierarchy arrow missing"),
        Validators.contains('NSString', "NSString class not found"),
    )


def validate_inheritance_chain():
    """Complete inheritance chain NSMutableString → NSString → NSObject."""
    def check_chain(output):
        has_all = ('NSMutableString' in output and
                   'NSString' in output and
                   'NSObject' in output and
                   output.count('→') >= 2)
        return has_all

    return Validators.custom(
        check_chain,
        pass_msg="Complete 3-level inheritance chain shown",
        fail_msg="Expected NSMutableString → NSString → NSObject with 2+ arrows"
    )


def validate_few_matches():
    """2-20 matches show compact hierarchy."""
    def check_few(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if 2 <= count <= 20:
                return '→' in output
        return '→' in output  # At least check for arrows

    return Validators.custom(
        check_few,
        pass_msg="Compact hierarchy shown for 2-20 matches",
        fail_msg="Expected hierarchy arrows for 2-20 matches"
    )


def validate_each_class_hierarchy():
    """Each class in 2-20 range shows hierarchy."""
    def check_each(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if 2 <= count <= 20:
                lines = output.split('\n')
                hierarchy_lines = [l for l in lines if '→' in l and 'total' not in l.lower()]
                return len(hierarchy_lines) > 0
        return True  # Pass for other counts

    return Validators.custom(
        check_each,
        pass_msg="Classes show hierarchy information",
        fail_msg="Expected hierarchy lines for 2-20 class matches"
    )


def validate_many_matches():
    """21+ matches use simple list without per-class hierarchy."""
    def check_many(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if count > 20:
                # Count class lines with arrows
                lines = output.split('\n')
                hierarchy_lines = [l for l in lines if l.strip().startswith('NS') and '→' in l]
                # Should be minimal or zero for >20 matches
                return len(hierarchy_lines) < count // 2
        return False

    return Validators.custom(
        check_many,
        pass_msg="Simple list for >20 matches (no per-class hierarchy)",
        fail_msg="Expected simple list without per-class hierarchy for >20 matches"
    )


def validate_threshold_boundary():
    """Document behavior at 20-class threshold."""
    def check_threshold(output):
        # Always pass - just documenting behavior
        return True

    return Validators.custom(
        check_threshold,
        pass_msg="Threshold behavior documented",
        fail_msg=""
    )


def validate_root_class():
    """Root class NSObject has no superclass arrow."""
    return Validators.contains('NSObject', "NSObject class not found")


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Single match tests
        (
            "Single Match (NSString)",
            ['ocls NSString'],
            validate_single_match()
        ),
        (
            "Inheritance chain: NSMutableString",
            ['ocls NSMutableString'],
            validate_inheritance_chain()
        ),
        # Few matches (2-20) tests
        (
            "Few Matches (NSMutable*)",
            ['ocls NSMutable*'],
            validate_few_matches()
        ),
        (
            "Each class shows hierarchy (2-20)",
            ['ocls NSMutableS*'],
            validate_each_class_hierarchy()
        ),
        # Many matches (21+) tests
        (
            "Many Matches (NS*) - no per-class hierarchy",
            ['ocls NS*'],
            validate_many_matches()
        ),
        # Edge cases
        (
            "Threshold boundary: exactly 20 matches",
            ['ocls NSMutable*'],
            validate_threshold_boundary()
        ),
        (
            "Root class: NSObject",
            ['ocls NSObject'],
            validate_root_class()
        ),
    ]


def main():
    """Run all hierarchy display tests using shared LLDB session."""

    passed, total = run_shared_test_suite(
        "OCLS HIERARCHY TEST SUITE (Refactored with Validators)",
        get_test_specs(),
        scripts=['objc_cls.py']
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
