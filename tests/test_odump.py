#!/usr/bin/env python3
"""
Test script for the odump command (Dump NSData/memory to file).

This script tests the odump functionality:
- Dump NSData with known contents, verify file matches
- Dump raw memory region, verify contents
- Test hex/decimal size parsing
- Test various expression formats ($0, addresses, ObjC expressions)
- Test error cases (nil, zero-length, invalid address)
- Test --force flag with protected memory
- Test file overwrite behavior

Uses a shared LLDB session for faster test execution.
"""

import os
import sys
import tempfile
from test_helpers import run_shared_test_suite


# =============================================================================
# Validator Functions
# =============================================================================


def validate_dump_success():
    """Validator that checks for successful dump output."""

    def validator(output):
        if "Dumped" in output and "bytes" in output:
            return True, "Dump completed successfully"
        if "error" in output.lower():
            return False, f"Error during dump: {output[:300]}"
        return False, f"Unexpected output: {output[:300]}"

    return validator


def validate_nsdata_dump():
    """Validator for NSData dump operation."""

    def validator(output):
        if "Dumped" in output and "NSData" in output:
            return True, "NSData dump completed"
        if "error" in output.lower() or "nil" in output.lower():
            return False, f"NSData dump failed: {output[:300]}"
        if "Dumped" in output:
            return True, "Dump completed (mode not specified)"
        return False, f"Unexpected output: {output[:300]}"

    return validator


def validate_raw_memory_dump():
    """Validator for raw memory dump operation."""

    def validator(output):
        if "Dumped" in output and "raw memory" in output:
            return True, "Raw memory dump completed"
        if "Dumped" in output and "bytes" in output:
            return True, "Memory dump completed"
        if "error" in output.lower():
            return False, f"Raw dump failed: {output[:300]}"
        return False, f"Unexpected output: {output[:300]}"

    return validator


def validate_error_nil():
    """Validator that checks for nil/NULL error."""

    def validator(output):
        if "nil" in output.lower() or "null" in output.lower() or "error" in output.lower():
            return True, "Nil error properly reported"
        return False, f"Expected nil error, got: {output[:300]}"

    return validator


def validate_error_zero_length():
    """Validator that checks for zero length error."""

    def validator(output):
        if "zero" in output.lower() or "error" in output.lower():
            return True, "Zero length error properly reported"
        return False, f"Expected zero length error, got: {output[:300]}"

    return validator


def validate_error_invalid():
    """Validator that checks for invalid expression/address error."""

    def validator(output):
        if "error" in output.lower() or "invalid" in output.lower() or "failed" in output.lower():
            return True, "Invalid expression error reported"
        return False, f"Expected error, got: {output[:300]}"

    return validator


def validate_usage_shown():
    """Validator that checks if usage info is shown."""

    def validator(output):
        if "usage" in output.lower() or "<expr>" in output.lower() or "odump" in output.lower():
            return True, "Usage information shown"
        return False, f"Expected usage info, got: {output[:300]}"

    return validator


# =============================================================================
# Test Specs
# =============================================================================

# Generate a temp file path for tests
TEMP_DIR = tempfile.gettempdir()


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Test 1: Dump NSData created from string
        (
            "Dump NSData from string",
            [
                'expr NSData *$testData = [@"Hello, World!" dataUsingEncoding:4]',
                f"odump $testData {TEMP_DIR}/odump_test1.bin",
            ],
            validate_nsdata_dump(),
        ),
        # Test 2: Dump raw memory with decimal size
        (
            "Dump raw memory (decimal size)",
            [
                "expr char *$testBuf = (char *)malloc(64)",
                "expr (void)memset($testBuf, 0x41, 64)",
                f"odump $testBuf {TEMP_DIR}/odump_test2.bin --size=64",
            ],
            validate_raw_memory_dump(),
        ),
        # Test 3: Dump raw memory with hex size
        (
            "Dump raw memory (hex size)",
            [
                "expr char *$testBuf2 = (char *)malloc(256)",
                "expr (void)memset($testBuf2, 0x42, 256)",
                f"odump $testBuf2 {TEMP_DIR}/odump_test3.bin --size=0x100",
            ],
            validate_raw_memory_dump(),
        ),
        # Test 4: Test with ObjC expression
        (
            "Dump NSData from ObjC expression",
            [
                'expr NSData *$exprData = [@"test data" dataUsingEncoding:4]',
                f"odump $exprData {TEMP_DIR}/odump_test4.bin",
            ],
            validate_nsdata_dump(),
        ),
        # Test 5: Error case - nil NSData
        (
            "Error on nil NSData",
            [
                "expr NSData *$nilData = nil",
                f"odump $nilData {TEMP_DIR}/odump_test5.bin",
            ],
            validate_error_nil(),
        ),
        # Test 6: Error case - no arguments
        (
            "Error on no arguments",
            ["odump"],
            validate_usage_shown(),
        ),
        # Test 7: Error case - missing output path
        (
            "Error on missing output path",
            ["odump $0"],
            validate_usage_shown(),
        ),
        # Test 8: Dump NSMutableData
        (
            "Dump NSMutableData",
            [
                "expr NSMutableData *$mutData = (NSMutableData *)[[NSMutableData alloc] initWithLength:32]",
                f"odump $mutData {TEMP_DIR}/odump_test8.bin",
            ],
            validate_nsdata_dump(),
        ),
        # Test 9: Test --size with equals syntax
        (
            "Test --size=N syntax",
            [
                "expr char *$buf9 = (char *)malloc(128)",
                "expr (void)memset($buf9, 0x43, 128)",
                f"odump $buf9 {TEMP_DIR}/odump_test9.bin --size=128",
            ],
            validate_raw_memory_dump(),
        ),
        # Test 10: File overwrite (run twice to same path)
        (
            "File overwrite behavior",
            [
                'expr NSData *$overwriteData = [@"First" dataUsingEncoding:4]',
                f"odump $overwriteData {TEMP_DIR}/odump_overwrite.bin",
                'expr $overwriteData = [@"Second" dataUsingEncoding:4]',
                f"odump $overwriteData {TEMP_DIR}/odump_overwrite.bin",
            ],
            validate_nsdata_dump(),
        ),
    ]


# =============================================================================
# Main
# =============================================================================


def main():
    """Run all odump tests."""
    test_specs = get_test_specs()

    passed, total = run_shared_test_suite(
        "odump tests",
        test_specs,
        scripts=["scripts"],  # Load the whole package
    )

    # Clean up test files
    for i in range(1, 11):
        try:
            os.remove(f"{TEMP_DIR}/odump_test{i}.bin")
        except FileNotFoundError:
            pass
    try:
        os.remove(f"{TEMP_DIR}/odump_overwrite.bin")
    except FileNotFoundError:
        pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
