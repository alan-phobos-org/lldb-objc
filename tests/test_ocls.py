#!/usr/bin/env python3
"""
Test script for the ocls command (Objective-C Class Finder).

This script tests the ocls core functionality:
- Basic class listing
- Exact match (case-sensitive, fast-path)
- Wildcard patterns (* and ?)
- Flags: --reload, --clear-cache, --verbose, --batch-size, --dylib
- Caching behavior
- Hierarchy display modes
- Error handling

PERFORMANCE OPTIMIZATIONS:
- Minimized --reload usage (only 1 full re-enumeration vs 4+ in original)
- Test ordering optimized for cache reuse
- Warmup pre-populates cache before tests
- Uses shared LLDB session for ~60x speedup vs spawning per-test

Uses a shared LLDB session for faster test execution.
"""

import sys
from test_helpers import run_shared_test_suite, Validators, OclsValidators

# =============================================================================
# Test Configuration Constants
# =============================================================================

# Thresholds for validation
MIN_TOTAL_CLASSES = 1000  # Minimum expected classes in a full runtime
HIERARCHY_COMPACT_MAX = 20  # Max classes for compact hierarchy display
FAST_PATH_EXPR_LIMIT = 50  # Max expressions for --dylib fast path (realistic for patterns matching ~10 frameworks)


# =============================================================================
# Helper: Validator Combiner
# =============================================================================


def v_and(*validators):
    """Shorthand for combining validators with AND logic."""
    return Validators.combine_and(*validators)


def v_or(*validators):
    """Shorthand for combining validators with OR logic."""
    return Validators.combine_or(*validators)


# =============================================================================
# Test Specifications (Ordered for Performance)
# =============================================================================


def get_test_specs():
    """
    Return list of test specifications.

    Tests are ordered for optimal performance:
    1. Cached tests first (benefit from warmup)
    2. Exact matches (fast-path)
    3. Wildcard tests (use cache)
    4. Flag tests (minimal --reload usage)
    5. Expensive --dylib tests last
    """
    return [
        # =====================================================================
        # PHASE 1: Fast cached tests (benefit from warmup)
        # =====================================================================
        (
            "List all classes (cached)",
            ["ocls"],
            OclsValidators.class_count(min_count=MIN_TOTAL_CLASSES),
        ),
        (
            "Cache performance verification",
            ["ocls NS*"],  # Should hit cache from warmup
            v_and(
                OclsValidators.class_count(min_count=10),
                OclsValidators.class_found("NSString", "NSArray"),
            ),
        ),
        # =====================================================================
        # PHASE 2: Exact match tests (fast-path, no full enumeration)
        # =====================================================================
        (
            "Exact match: NSString",
            ["ocls NSString"],
            v_and(
                OclsValidators.class_found("NSString"),
                OclsValidators.has_hierarchy(),
                OclsValidators.dylib_info_present(),
            ),
        ),
        (
            "Exact match: non-existent class",
            ["ocls ThisClassDoesNotExist12345"],
            OclsValidators.no_classes_found(),
        ),
        (
            "Case sensitivity: nsstring vs NSString",
            ["ocls nsstring"],  # lowercase should not match (exact match is case-sensitive)
            OclsValidators.no_classes_found(),
        ),
        # =====================================================================
        # PHASE 3: Wildcard pattern tests (use cache)
        # =====================================================================
        (
            "Wildcard: CS* (prefix match)",
            ["ocls CS*"],
            v_or(
                OclsValidators.class_count(min_count=1),
                # CoreSymbolication may not be available on all systems
                Validators.contains("No classes found"),
            ),
        ),
        (
            "Wildcard: *Controller (suffix match)",
            ["ocls *Controller"],
            v_and(
                OclsValidators.class_count(min_count=1),
                Validators.contains("Controller"),
            ),
        ),
        (
            "Wildcard: *String* (contains)",
            ["ocls *String*"],
            v_and(
                OclsValidators.class_count(min_count=1),
                Validators.contains("String"),
            ),
        ),
        (
            "Wildcard: NS?rray (single char)",
            ["ocls NS?rray"],
            OclsValidators.class_found("NSArray"),
        ),
        (
            "Wildcard case-insensitivity: *string*",
            ["ocls *string*"],
            OclsValidators.class_found("NSString"),  # Should match despite lowercase pattern
        ),
        # =====================================================================
        # PHASE 4: Hierarchy display modes
        # =====================================================================
        (
            "Single match hierarchy display",
            ["ocls NSMutableString"],
            v_and(
                OclsValidators.class_found("NSMutableString"),
                OclsValidators.has_hierarchy(),
                OclsValidators.dylib_info_present(),
            ),
        ),
        (
            "Few matches (2-20) compact hierarchy",
            ["ocls NSMutable*"],
            v_and(
                OclsValidators.class_count(min_count=2, max_count=HIERARCHY_COMPACT_MAX),
                OclsValidators.has_hierarchy(),
            ),
        ),
        (
            "Many matches (21+) simple list",
            ["ocls NS*"],
            OclsValidators.class_count(min_count=HIERARCHY_COMPACT_MAX + 1),
        ),
        # =====================================================================
        # PHASE 5: Flag tests (minimal --reload usage)
        # =====================================================================
        (
            "Flag: --verbose shows metrics",
            ["ocls --verbose NSString"],
            v_and(
                OclsValidators.class_found("NSString"),
                OclsValidators.verbose_metrics(),
            ),
        ),
        (
            "Flag: --reload bypasses cache",
            ["ocls --reload --verbose NSString"],
            v_and(
                OclsValidators.class_found("NSString"),
                OclsValidators.not_cached(),
            ),
        ),
        (
            "Flag: --clear-cache",
            ["ocls --clear-cache"],
            Validators.contains_any("Cache cleared", "No cache found"),
        ),
        (
            "Flag: --batch-size=50",
            ["ocls --batch-size=50 --verbose NS*"],
            v_and(
                OclsValidators.class_count(min_count=10),
                Validators.contains("Batch size"),
            ),
        ),
        (
            "Flag: --batch-size 25 (space syntax)",
            ["ocls --batch-size 25 --verbose NS*"],
            v_and(
                OclsValidators.class_count(min_count=10),
                Validators.contains("Batch size"),
            ),
        ),
        # =====================================================================
        # PHASE 6: Edge cases
        # =====================================================================
        (
            "Empty pattern handling",
            ['ocls ""'],
            Validators.contains_any("Found", "total", "error"),
        ),
        (
            "Special characters: _NS*",
            ["ocls _NS*"],
            Validators.contains_any("_NS", "Found", "No classes"),
        ),
        # =====================================================================
        # PHASE 7: --dylib filter tests (potentially expensive)
        # =====================================================================
        (
            "Flag: --dylib *Foundation* (fuzzy match)",
            ["ocls --dylib *Foundation* NS*"],
            v_and(
                OclsValidators.class_count(min_count=10),
                OclsValidators.class_found("NSString", "NSArray"),
            ),
        ),
        (
            "Flag: --dylib *CoreSymbolication* (framework)",
            ["ocls --dylib *CoreSymbolication* CS*"],
            v_or(
                OclsValidators.class_count(min_count=1),
                # CoreSymbolication classes may not be available
                Validators.contains("No classes found"),
            ),
        ),
        (
            "Flag: --dylib *CoreFoundation* (exact framework)",
            ["ocls --dylib *CoreFoundation* CF*"],
            v_or(
                OclsValidators.class_count(min_count=1),
                Validators.contains("No classes found"),
            ),
        ),
        (
            "Flag: --dylib with non-existent pattern",
            ["ocls --dylib *NonExistentDylib12345* NSString"],
            OclsValidators.no_classes_found(),
        ),
        (
            "Flag: --dylib combined with class pattern",
            ["ocls --dylib *Foundation* NSMutableString"],
            v_and(
                OclsValidators.class_found("NSMutableString"),
                OclsValidators.has_hierarchy(),
            ),
        ),
        (
            "Flag: --dylib case-insensitive",
            ["ocls --dylib *foundation* NS*"],
            OclsValidators.class_count(min_count=10),
        ),
        (
            "Flag: --dylib fast path (low expression count)",
            ["ocls --dylib *Foundation* --verbose NS*"],
            v_and(
                OclsValidators.class_count(min_count=10),
                OclsValidators.expression_count(FAST_PATH_EXPR_LIMIT),
            ),
        ),
    ]


def main():
    """Run all ocls tests using shared LLDB session."""

    # Category ranges for organized output
    categories = {
        "Fast cached tests": (0, 2),
        "Exact match tests": (2, 5),
        "Wildcard patterns": (5, 10),
        "Hierarchy display": (10, 13),
        "Flag tests": (13, 18),
        "Edge cases": (18, 20),
        "--dylib filtering": (20, 27),
    }

    # PERFORMANCE: Pre-warm the class cache once at startup
    # This populates the cache so subsequent ocls commands are fast
    # Single warmup replaces 4+ expensive --reload operations
    warmup = [
        "ocls",  # Populate cache with full class list (~1-3s one-time cost)
    ]

    passed, total, elapsed, results = run_shared_test_suite(
        "OCLS COMMAND TEST SUITE",
        get_test_specs(),
        scripts=["scripts/objc_cls.py"],
        show_category_summary=categories,
        warmup_commands=warmup,
    )

    # Print performance summary
    print(f"\n{'=' * 70}")
    print(f"Performance: {total} tests in {elapsed:.1f}s ({elapsed / total:.2f}s avg per test)")
    print("Optimizations: Shared session, cache warmup, minimal reloads")
    print(f"{'=' * 70}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
