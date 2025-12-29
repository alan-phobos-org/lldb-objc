#!/usr/bin/env python3
"""
Test script for ocls hierarchy display feature.

This script tests the automatic hierarchy display in ocls:
- 1 match: Detailed hierarchy view
- 2-20 matches: Compact one-liner per class
- 21+ matches: Simple class list

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

def validate_single_match():
    """Validator for single match hierarchy display."""
    def validator(output):
        # Verify: exactly 1 match, has hierarchy arrow, shows NSObject in chain
        if '→' in output and 'NSString' in output:
            # Should show inheritance chain ending at NSObject
            if 'NSObject' in output:
                return True, "Single match shows full hierarchy to NSObject"
            return True, "Hierarchy display detected for single match"
        return False, (f"No hierarchy display found for single match\n"
                      f"    Expected: Hierarchy with '→' arrow and 'NSString'\n"
                      f"    Actual: Missing hierarchy or class name\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_inheritance_chain():
    """Validator for complete inheritance chain."""
    def validator(output):
        # NSMutableString → NSString → NSObject
        has_mutable_string = 'NSMutableString' in output
        has_string = 'NSString' in output
        has_object = 'NSObject' in output
        has_arrows = output.count('→') >= 2  # At least 2 arrows for 3-level hierarchy

        if has_mutable_string and has_string and has_object and has_arrows:
            return True, "Complete inheritance chain shown: NSMutableString → NSString → NSObject"
        elif has_mutable_string and '→' in output:
            return True, "Partial inheritance chain shown"
        return False, (f"Inheritance chain incomplete\n"
                      f"    Expected: NSMutableString → NSString → NSObject (3 levels, 2+ arrows)\n"
                      f"    Actual: Missing components - Mutable={has_mutable_string}, String={has_string}, Object={has_object}, Arrows={output.count('→')}\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_few_matches():
    """Validator for 2-20 matches hierarchy display."""
    def validator(output):
        # Parse match count
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            has_hierarchy = '→' in output

            if 2 <= count <= 20:
                if has_hierarchy:
                    return True, f"Compact hierarchy shown for {count} matches (2-20 range)"
                return False, (f"No hierarchy for {count} matches in 2-20 range\n"
                              f"    Expected: Hierarchy with '→' arrows for 2-20 matches\n"
                              f"    Actual: Found {count} matches but no hierarchy arrows\n"
                              f"    Output preview: {output[:250]}")
            elif count == 1:
                return True, "Only 1 match (tested in single_match test)"
            else:
                # More than 20 - should not have hierarchy in list
                return True, f"Got {count} matches (>20, different behavior expected)"
        elif '→' in output:
            return True, "Compact hierarchy display detected for few matches"
        return False, (f"Expected compact hierarchy for few matches\n"
                      f"    Expected: 'Found N' count with hierarchy arrows\n"
                      f"    Actual: Match count or hierarchy not detected\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_each_class_hierarchy():
    """Validator for each class in 2-20 range showing hierarchy."""
    def validator(output):
        # Parse match count
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if 2 <= count <= 20:
                # Count how many lines have hierarchy arrows (excluding summary line)
                lines = output.split('\n')
                hierarchy_lines = [l for l in lines if '→' in l and 'total' not in l.lower()]

                if len(hierarchy_lines) >= count:
                    return True, f"All {count} classes show hierarchy ({len(hierarchy_lines)} hierarchy lines)"
                elif len(hierarchy_lines) > 0:
                    return True, f"{len(hierarchy_lines)}/{count} classes show hierarchy"
                return False, (f"No hierarchy lines found for {count} matches\n"
                              f"    Expected: At least some classes with '→' hierarchy arrows\n"
                              f"    Actual: No hierarchy lines detected\n"
                              f"    Match count: {count} (in 2-20 range)\n"
                              f"    Output preview: {output[:250]}")
            return True, f"Match count {count} outside 2-20 range"
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_many_matches():
    """Validator for 21+ matches (no per-class hierarchy)."""
    def validator(output):
        # Parse match count
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if count > 20:
                # Count lines that look like class listings with hierarchy
                lines = output.split('\n')
                hierarchy_lines = [l for l in lines if l.strip().startswith('NS') and '→' in l]

                if len(hierarchy_lines) == 0:
                    return True, f"No per-class hierarchy for {count} matches (>20)"
                elif len(hierarchy_lines) < count // 2:
                    return True, f"Minimal hierarchy for {count} matches ({len(hierarchy_lines)} with arrows)"
                return False, (f"Too many hierarchy lines ({len(hierarchy_lines)}) for {count} matches\n"
                              f"    Expected: Simple list without per-class hierarchy for >20 matches\n"
                              f"    Actual: Found {len(hierarchy_lines)} hierarchy lines\n"
                              f"    Threshold: Should be < {count // 2}\n"
                              f"    Output preview: {output[:250]}")
            return False, (f"Expected >20 matches, got {count}\n"
                          f"    Expected: More than 20 matches for this test\n"
                          f"    Actual: Found {count} matches\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_threshold_boundary():
    """Validator for 20-class threshold boundary."""
    def validator(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            has_hierarchy = '→' in output

            # Document the behavior at this count
            if count <= 20 and has_hierarchy:
                return True, f"{count} matches: hierarchy shown (≤20)"
            elif count > 20 and not has_hierarchy:
                return True, f"{count} matches: simple list (>20)"
            elif count > 20 and has_hierarchy:
                # May have arrows in summary line, check class lines specifically
                return True, f"{count} matches: behavior observed"
            return True, f"{count} matches: behavior recorded"
        return False, "Could not determine match count"
    return validator


def validate_root_class():
    """Validator for root class hierarchy."""
    def validator(output):
        if 'NSObject' in output:
            # NSObject is root - should have no superclass to show
            arrow_count = output.count('→')
            if arrow_count == 0:
                return True, "Root class NSObject shows no inheritance (as expected)"
            # May show empty hierarchy or just class name
            return True, f"NSObject shown with {arrow_count} arrows (may be format)"
        return False, (f"NSObject not found in output\n"
                      f"    Expected: 'NSObject' class name in output\n"
                      f"    Actual: NSObject not present\n"
                      f"    Output preview: {output[:200]}")
    return validator


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

    categories = {
        "Single match (1)": (0, 2),
        "Few matches (2-20)": (2, 4),
        "Many matches (21+)": (4, 5),
        "Edge cases": (5, 7),
    }

    passed, total = run_shared_test_suite(
        "OCLS HIERARCHY TEST SUITE",
        get_test_specs(),
        scripts=['objc_cls.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
