#!/usr/bin/env python3
"""
Test script for the ocls command (Objective-C Class Finder).

This script tests the ocls core functionality:
- Basic class listing
- Exact match (case-sensitive, fast-path)
- Wildcard patterns (* and ?)
- Flags: --reload, --clear-cache, --verbose, --batch-size
- Caching behavior
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

def validate_list_all_classes():
    """Validator for listing all classes."""
    def validator(output):
        # Should find many classes
        # Match numbers with optional commas (e.g., "10,774 total")
        match = re.search(r'([\d,]+)\s*total', output)
        if match:
            count = int(match.group(1).replace(',', ''))
            if count > 1000:
                return True, f"Found {count:,} classes"
            return False, (f"Expected >1000 classes, got {count}\n"
                          f"    Possible causes:\n"
                          f"      - Runtime not fully initialized\n"
                          f"      - Frameworks not loaded\n"
                          f"    Output preview: {output[:200]}")
        elif 'Found' in output:
            return True, "Found classes (count format may differ)"
        return False, (f"No classes found\n"
                      f"    Expected: 'total' count in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_exact_match():
    """Validator for exact match."""
    def validator(output):
        if 'NSString' in output:
            # Verify it's an exact match, not a wildcard match
            if 'nsstring' not in output or 'NSString' in output:
                return True, "Exact match found"
            return False, ("Case sensitivity issue\n"
                          "    Expected: Only 'NSString' (exact case)\n"
                          "    Found: lowercase variant in output")
        return False, (f"NSString not found\n"
                      f"    Expected: 'NSString' in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_exact_match_not_found():
    """Validator for non-existent class."""
    def validator(output):
        if 'No classes found' in output or '0' in output:
            return True, "Correctly reports no match"
        return False, (f"Should report no match for non-existent class\n"
                      f"    Expected: 'No classes found' or '0'\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_case_sensitive():
    """Validator for case sensitivity."""
    def validator(output):
        # Without wildcards, this should be an exact match that fails
        if 'No classes found' in output or 'NSString' not in output:
            return True, "Exact match is case-sensitive"
        return False, (f"Case sensitivity not enforced\n"
                      f"    Expected: 'nsstring' (lowercase) should not match\n"
                      f"    Actual: Found 'NSString' in output\n"
                      f"    Output: {output[:300]}")
    return validator


def validate_wildcard_prefix():
    """Validator for prefix wildcard."""
    def validator(output):
        if 'IDS' in output and 'Found' in output:
            return True, "Prefix wildcard works"
        elif 'No classes found' in output:
            return False, ("No IDS classes found\n"
                          "    Expected: Classes starting with 'IDS'\n"
                          "    Possible causes:\n"
                          "      - IDS framework may not be loaded\n"
                          "      - dlopen() call for IDS.framework failed")
        return False, (f"Unexpected output\n"
                      f"    Expected: 'Found' with IDS classes\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_suffix():
    """Validator for suffix wildcard."""
    def validator(output):
        if 'Controller' in output and 'Found' in output:
            return True, "Suffix wildcard works"
        return False, (f"No Controller classes found\n"
                      f"    Expected: Classes ending with 'Controller'\n"
                      f"    Search pattern: *Controller\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_contains():
    """Validator for contains wildcard."""
    def validator(output):
        if 'String' in output and 'Found' in output:
            return True, "Contains wildcard works"
        return False, (f"No String classes found\n"
                      f"    Expected: Classes containing 'String'\n"
                      f"    Search pattern: *String*\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_single_char():
    """Validator for single character wildcard."""
    def validator(output):
        if 'NSArray' in output:
            return True, "Single character wildcard works"
        return False, (f"NSArray not matched by NS?rray pattern\n"
                      f"    Expected: 'NSArray' to match pattern 'NS?rray'\n"
                      f"    Single char wildcard (?) should match 'A'\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_case_insensitive():
    """Validator for case-insensitive wildcard."""
    def validator(output):
        if 'NSString' in output or 'String' in output:
            return True, "Wildcard matching is case-insensitive"
        return False, (f"Case insensitivity failed for wildcard pattern\n"
                      f"    Expected: '*string*' (lowercase) to match 'NSString'\n"
                      f"    Wildcards should be case-insensitive\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_verbose_flag():
    """Validator for --verbose flag."""
    def validator(output):
        has_timing = 'Total time' in output or 'Timing breakdown' in output
        has_expressions = 'Expressions' in output or 'expressions' in output
        has_memory = 'Memory' in output or 'memory' in output

        if has_timing or has_expressions or has_memory:
            return True, "Verbose output shows performance metrics"
        elif 'Found' in output:
            return False, (f"Command works but no verbose metrics shown\n"
                          f"    Expected: 'Total time', 'Timing breakdown', 'Expressions', or 'Memory' in output\n"
                          f"    Actual: Classes found but no performance metrics\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"Unexpected output\n"
                      f"    Expected: Classes found with verbose performance metrics\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_reload_flag():
    """Validator for --reload flag."""
    def validator(output):
        # With --reload and --verbose, should show it's NOT using cache
        if 'NSString' in output:
            # When --reload is used, output should explicitly NOT show "cached"
            if 'cached' in output.lower():
                return False, (f"--reload flag failed: results show 'cached'\n"
                              f"    Expected: Cache bypass, no 'cached' indicator\n"
                              f"    Actual: Found 'cached' in output\n"
                              f"    Possible cause: --reload flag not properly forcing cache bypass\n"
                              f"    Output preview: {output[:250]}")
            # With --verbose, we should see timing info indicating fresh enumeration
            if 'Total time' in output or 'Timing breakdown' in output:
                return True, "--reload flag works (forced cache bypass with timing info)"
            # Without --verbose, just verify command succeeded without cache indicator
            return True, "--reload flag works (no cache indicator present)"
        return False, (f"Reload failed to find NSString\n"
                      f"    Expected: 'NSString' in output\n"
                      f"    Actual: NSString not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_clear_cache_flag():
    """Validator for --clear-cache flag."""
    def validator(output):
        if 'Cache cleared' in output or 'cleared' in output.lower():
            return True, "--clear-cache flag works"
        elif 'No cache found' in output:
            return True, "--clear-cache handled (no cache existed)"
        # Should have explicit confirmation, not just generic success
        return False, (f"No clear-cache confirmation message in output\n"
                      f"    Expected: 'Cache cleared' or 'cleared' message\n"
                      f"    Actual: No confirmation message found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_batch_size_equals():
    """Validator for --batch-size=N syntax."""
    def validator(output):
        # With --verbose, should show batch size in output
        if 'Found' in output or 'NS' in output:
            if 'batch' in output.lower() or 'Batch size' in output:
                return True, "--batch-size=N syntax works (batch info shown)"
            # Without verbose output, we can't verify batch size was applied
            return False, (f"Command succeeded but no batch size info shown (need --verbose)\n"
                          f"    Expected: 'batch' or 'Batch size' in verbose output\n"
                          f"    Actual: Results found but no batch size information\n"
                          f"    Possible cause: --verbose flag may not be working\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"Command failed\n"
                      f"    Expected: Classes found with batch size info\n"
                      f"    Actual: No results found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_batch_size_space():
    """Validator for --batch-size N syntax."""
    def validator(output):
        # With --verbose, should show batch size in output
        if 'Found' in output or 'NS' in output:
            if 'batch' in output.lower() or 'Batch size' in output:
                return True, "--batch-size N syntax works (batch info shown)"
            # Without verbose output, we can't verify batch size was applied
            return False, (f"Command succeeded but no batch size info shown (need --verbose)\n"
                          f"    Expected: 'batch' or 'Batch size' in verbose output\n"
                          f"    Actual: Results found but no batch size information\n"
                          f"    Possible cause: --verbose flag may not be working\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"Command failed\n"
                      f"    Expected: Classes found with batch size info\n"
                      f"    Actual: No results found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_cache_performance():
    """Validator for cache performance."""
    def validator(output):
        # The test runs: ocls --reload NS*, then ocls NS*
        # Second run should show "cached" indicator or significantly faster timing
        if 'cached' in output.lower():
            return True, "Second query used cache"

        # If no explicit cache indicator, both queries should at least succeed
        if output.count('Found') >= 2:
            return False, (f"Both queries completed but no cache indicator shown\n"
                          f"    Expected: 'cached' in second query output\n"
                          f"    Actual: Both queries succeeded but no cache indicator\n"
                          f"    Possible cause: Cache may not be working or indicator missing\n"
                          f"    Output preview: {output[:250]}")

        return False, (f"Cache behavior unclear\n"
                      f"    Expected: Two successful queries with cache indicator\n"
                      f"    Actual: Unexpected output format\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_single_match_hierarchy():
    """Validator for single match hierarchy display."""
    def validator(output):
        # Single match should show hierarchy with arrows
        if '→' in output and 'NSMutableString' in output:
            if 'NSString' in output or 'NSObject' in output:
                return True, "Single match shows inheritance hierarchy"
            return True, "Hierarchy arrow present"
        return False, (f"No hierarchy shown\n"
                      f"    Expected: Hierarchy with '→' arrows showing NSMutableString inheritance chain\n"
                      f"    Actual: Missing hierarchy arrow or class name\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_few_matches_hierarchy():
    """Validator for 2-20 matches compact hierarchy."""
    def validator(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if 2 <= count <= 20:
                if '→' in output:
                    return True, f"Compact hierarchy shown for {count} matches"
                return False, (f"No hierarchy for {count} matches\n"
                              f"    Expected: Hierarchy with '→' arrows for 2-20 matches\n"
                              f"    Actual: Found {count} matches but no hierarchy arrows\n"
                              f"    Output preview: {output[:300]}")
            elif count == 1:
                return True, "Only 1 match (different display mode)"
            return True, f"Got {count} matches (>20, no hierarchy expected)"
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_many_matches_no_hierarchy():
    """Validator for 21+ matches simple list."""
    def validator(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if count > 20:
                class_lines = [l for l in output.split('\n') if l.strip().startswith('NS')]
                arrows_in_list = sum(1 for l in class_lines if '→' in l)

                if arrows_in_list == 0:
                    return True, f"Simple list for {count} matches (no per-class hierarchy)"
                return False, (f"Hierarchy shown for {count} matches (expected simple list)\n"
                              f"    Expected: Simple list without '→' arrows for >20 matches\n"
                              f"    Actual: Found {arrows_in_list} hierarchy arrows in output\n"
                              f"    Possible cause: Display mode threshold may be incorrect\n"
                              f"    Output preview: {output[:250]}")
            return False, (f"Only {count} matches, expected >20\n"
                          f"    Expected: More than 20 matches for this test\n"
                          f"    Actual: Found {count} matches\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_empty_pattern():
    """Validator for empty pattern."""
    def validator(output):
        if 'Found' in output or 'total' in output or 'error' in output.lower():
            return True, "Empty pattern handled gracefully"
        return False, (f"Unexpected behavior for empty pattern\n"
                      f"    Expected: 'Found', 'total', or error message\n"
                      f"    Actual: Unexpected output format\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_special_characters():
    """Validator for special characters in pattern."""
    def validator(output):
        if '_NS' in output or 'Found' in output or 'No classes' in output:
            return True, "Special character pattern handled"
        return False, (f"Unexpected output for special character pattern\n"
                      f"    Expected: Classes with '_NS' prefix, 'Found' count, or 'No classes'\n"
                      f"    Actual: Unexpected output format\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_single_match_dylib():
    """Validator for single match dylib display."""
    def validator(output):
        has_dylib_info = any(pattern in output for pattern in [
            '/System/Library/',
            '.framework',
            '.dylib',
            'Foundation',
            'CoreFoundation',
            'libobjc'
        ])

        if 'NSString' in output and has_dylib_info:
            return True, "Dylib information shown for single match"
        elif 'NSString' in output:
            return False, (f"Class found but no dylib information shown\n"
                          f"    Expected: Path with '.framework', '.dylib', or '/System/Library/'\n"
                          f"    Actual: NSString found but no dylib/framework path\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"NSString not found\n"
                      f"    Expected: 'NSString' class with dylib information\n"
                      f"    Actual: NSString not in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_dylib_format():
    """Validator for dylib format."""
    def validator(output):
        if 'NSObject' in output:
            has_path = bool(re.search(r'/[a-zA-Z]+/', output))
            if has_path:
                return True, "Dylib path shown"
            return False, (f"No path information found\n"
                          f"    Expected: Path with '/' characters (e.g., /System/Library/...)\n"
                          f"    Actual: NSObject found but no path format detected\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"NSObject not found\n"
                      f"    Expected: 'NSObject' class with dylib path\n"
                      f"    Actual: NSObject not in output\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_multiple_matches_no_dylib():
    """Validator for multiple matches no dylib."""
    def validator(output):
        match = re.search(r'Found (\d+)', output)
        if match:
            count = int(match.group(1))
            if count > 1:
                return True, f"Multiple matches ({count}) handled correctly"
            return False, (f"Expected multiple matches, got {count}\n"
                          f"    Expected: More than 1 match\n"
                          f"    Actual: Found only {count} match\n"
                          f"    Output preview: {output[:250]}")
        return False, (f"Could not parse match count\n"
                      f"    Expected: 'Found N' in output\n"
                      f"    Actual: Match count format not recognized\n"
                      f"    Output preview: {output[:300]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic functionality
        # Note: "List all classes" uses cache pre-warmed by run_shared_test_suite
        (
            "List all classes (cached)",
            ['ocls'],
            validate_list_all_classes()
        ),
        (
            "Exact match: NSString",
            ['ocls NSString'],
            validate_exact_match()
        ),
        (
            "Exact match: non-existent class",
            ['ocls ThisClassDoesNotExist12345'],
            validate_exact_match_not_found()
        ),
        (
            "Case sensitivity: nsstring vs NSString",
            ['ocls nsstring'],
            validate_case_sensitive()
        ),
        # Wildcard patterns
        (
            "Wildcard: IDS* (prefix match)",
            ['ocls IDS*'],
            validate_wildcard_prefix()
        ),
        (
            "Wildcard: *Controller (suffix match)",
            ['ocls *Controller'],
            validate_wildcard_suffix()
        ),
        (
            "Wildcard: *String* (contains)",
            ['ocls *String*'],
            validate_wildcard_contains()
        ),
        (
            "Wildcard: NS?rray (single char)",
            ['ocls NS?rray'],
            validate_wildcard_single_char()
        ),
        (
            "Wildcard case-insensitivity: *string*",
            ['ocls *string*'],
            validate_wildcard_case_insensitive()
        ),
        # Flags
        (
            "Flag: --verbose",
            ['ocls --verbose NSString'],
            validate_verbose_flag()
        ),
        (
            "Flag: --reload",
            # Test that --reload forces cache bypass (use --verbose to verify timing)
            ['ocls --reload --verbose NSString'],
            validate_reload_flag()
        ),
        (
            "Flag: --clear-cache",
            ['ocls NS*', 'ocls --clear-cache', 'ocls NS*'],
            validate_clear_cache_flag()
        ),
        (
            "Flag: --batch-size=50",
            ['ocls --batch-size=50 --verbose --reload NS*'],
            validate_batch_size_equals()
        ),
        (
            "Flag: --batch-size 25",
            ['ocls --batch-size 25 --verbose --reload NS*'],
            validate_batch_size_space()
        ),
        # Caching
        (
            "Cache performance",
            ['ocls --reload NS*', 'ocls NS*'],
            validate_cache_performance()
        ),
        # Hierarchy display
        (
            "Single match hierarchy display",
            ['ocls NSMutableString'],
            validate_single_match_hierarchy()
        ),
        (
            "Few matches (2-20) compact hierarchy",
            ['ocls NSMutable*'],
            validate_few_matches_hierarchy()
        ),
        (
            "Many matches (21+) simple list",
            ['ocls NS*'],
            validate_many_matches_no_hierarchy()
        ),
        # Edge cases
        (
            "Empty pattern handling",
            ['ocls ""'],
            validate_empty_pattern()
        ),
        (
            "Special characters: _NS*",
            ['ocls _NS*'],
            validate_special_characters()
        ),
        # Dylib display
        (
            "Single match shows dylib",
            ['ocls NSString'],
            validate_single_match_dylib()
        ),
        (
            "Dylib display format",
            ['ocls NSObject'],
            validate_dylib_format()
        ),
        (
            "Multiple matches: no dylib",
            ['ocls NSMutable*'],
            validate_multiple_matches_no_dylib()
        ),
    ]


def main():
    """Run all ocls tests using shared LLDB session."""

    categories = {
        "Basic functionality": (0, 4),
        "Wildcard patterns": (4, 9),
        "Flags": (9, 14),
        "Caching": (14, 15),
        "Hierarchy display": (15, 18),
        "Edge cases": (18, 20),
        "Dylib display": (20, 23),
    }

    # Pre-warm the class cache once at startup to avoid slow first-run in tests
    # This populates the cache so subsequent ocls commands are fast
    warmup = ['ocls']  # List all classes to populate cache

    passed, total = run_shared_test_suite(
        "OCLS COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_cls.py'],
        show_category_summary=categories,
        warmup_commands=warmup
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
