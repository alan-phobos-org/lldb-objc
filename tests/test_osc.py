#!/usr/bin/env python3
"""
Test script for the osc command (Dyld Shared Cache Information).

This script tests the osc functionality:
- Display shared cache base address, size, UUID, and path
- Verify all expected fields are present in output
- Validate addresses are properly formatted and in valid ranges
- Verify cache slide calculation (base address with ASLR)
- Test verbose mode

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
from test_helpers import run_shared_test_suite


# =============================================================================
# Helper Functions
# =============================================================================


def extract_hex_value(output, field_name):
    """Extract a hex value from output for a given field name."""
    # Handle both single value and range formats
    # Single: "Field: 0x123456"
    # Range: "Field: 0x123456 - 0x789abc"
    pattern = rf"{re.escape(field_name)}\s+(?:\x1b\[90m)?0x([0-9a-fA-F]+)"
    match = re.search(pattern, output)
    if match:
        return int(match.group(1), 16)
    return None


def extract_range_values(output):
    """Extract base and end addresses from Range field."""
    # Range: 0x0000000187bfc000 - 0x00000002d61c0000
    pattern = r"Range:.*?0x([0-9a-fA-F]+)\s*-\s*0x([0-9a-fA-F]+)"
    match = re.search(pattern, output)
    if match:
        base = int(match.group(1), 16)
        end = int(match.group(2), 16)
        return base, end
    return None, None


def extract_size_bytes(output):
    """Extract size in bytes from output."""
    # Look for "Size: X.XX GB (NNN bytes)" or similar
    pattern = r"Size:.*?\(([0-9,]+)\s+bytes\)"
    match = re.search(pattern, output)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def extract_uuid(output):
    """Extract UUID from output."""
    pattern = r"UUID:\s+([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})"
    match = re.search(pattern, output)
    if match:
        return match.group(1)
    return None


# =============================================================================
# Validator Functions
# =============================================================================


def validate_shared_cache_info():
    """Validator that checks for shared cache information output."""

    def validator(output):
        required_fields = [
            "Dyld Shared Cache",
            "Range:",
            "Size:",
        ]

        missing_fields = []
        for field in required_fields:
            if field not in output:
                missing_fields.append(field)

        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"

        # Check for error messages
        if "error" in output.lower() and "Range:" not in output:
            return False, f"Error in output: {output[:300]}"

        # Verify base address format (should be hex)
        if "0x" not in output:
            return False, "No hex address found in output"

        return True, "Shared cache info displayed successfully"

    return validator


def validate_cache_addresses():
    """Validator that verifies cache addresses are valid and consistent."""

    def validator(output):
        base, end = extract_range_values(output)
        size = extract_size_bytes(output)

        if base is None:
            return False, f"Could not extract base address\n\n  Output (first 500 chars):\n  {output[:500]}"

        if end is None:
            return False, f"Could not extract end address\n\n  Output (first 500 chars):\n  {output[:500]}"

        if size is None:
            return False, f"Could not extract size in bytes\n\n  Output (first 500 chars):\n  {output[:500]}"

        # Verify end = base + size
        expected_end = base + size
        if end != expected_end:
            return False, f"Address mismatch: end (0x{end:x}) != base + size (0x{expected_end:x})"

        # Verify base address is page-aligned (16KB = 0x4000 on modern macOS)
        page_size = 0x4000
        if base % page_size != 0:
            return False, f"Base address 0x{base:x} is not page-aligned (0x{page_size:x})"

        # Verify base is in reasonable range for shared cache
        # On arm64 macOS, shared cache is typically at 0x180000000 and above
        # On x86_64, it varies but should be in high memory
        min_base = 0x100000000  # At least 4GB
        if base < min_base:
            return False, f"Base address 0x{base:x} is suspiciously low (< 0x{min_base:x})"

        # Verify size is reasonable (should be at least 100MB, less than 10GB)
        min_size = 100 * 1024 * 1024  # 100 MB
        max_size = 10 * 1024 * 1024 * 1024  # 10 GB
        if size < min_size:
            return False, f"Size {size:,} bytes is too small (< {min_size:,})"
        if size > max_size:
            return False, f"Size {size:,} bytes is too large (> {max_size:,})"

        return True, f"Valid addresses: base=0x{base:x}, end=0x{end:x}, size={size:,} bytes"

    return validator


def validate_cache_slide():
    """Validator that verifies the cache slide is calculated and displayed."""

    def validator(output):
        # Check for the slide fields
        if "Preferred base:" not in output:
            return False, "Missing 'Preferred base:' field"

        if "ASLR slide:" not in output:
            return False, "Missing 'ASLR slide:' field"

        preferred_base = extract_hex_value(output, "Preferred base:")
        slide = extract_hex_value(output, "ASLR slide:")
        actual_base, _ = extract_range_values(output)

        if preferred_base is None:
            return False, "Could not extract preferred base address"

        if slide is None:
            return False, "Could not extract ASLR slide value"

        if actual_base is None:
            return False, "Could not extract actual loaded base address"

        # Verify slide calculation: actual_base = preferred_base + slide
        expected_actual = preferred_base + slide
        if actual_base != expected_actual:
            msg = (
                f"Slide calculation error: 0x{actual_base:x} != "
                f"0x{preferred_base:x} + 0x{slide:x} (0x{expected_actual:x})"
            )
            return False, msg

        # Verify preferred base is reasonable for the platform
        # arm64/arm64e: typically 0x180000000
        # x86_64: typically 0x7FFF20000000
        min_preferred = 0x100000000  # At least 4GB
        if preferred_base < min_preferred:
            return False, f"Preferred base 0x{preferred_base:x} is suspiciously low"

        # Verify alignment (should be page-aligned, typically 16KB)
        page_size = 0x4000
        if slide % page_size != 0:
            return False, f"ASLR slide 0x{slide:x} is not page-aligned"

        return True, f"Valid slide: 0x{slide:x} (preferred: 0x{preferred_base:x}, actual: 0x{actual_base:x})"

    return validator


def validate_uuid_format():
    """Validator that checks UUID format is correct."""

    def validator(output):
        uuid = extract_uuid(output)

        if uuid is None:
            # UUID might be optional on some systems
            if "UUID:" not in output:
                return True, "UUID field not present (optional)"
            return False, "UUID field present but could not extract valid UUID"

        # Verify UUID format (8-4-4-4-12 hex digits)
        uuid_pattern = r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
        if not re.match(uuid_pattern, uuid):
            return False, f"Invalid UUID format: {uuid}"

        return True, f"Valid UUID: {uuid}"

    return validator


def validate_file_path():
    """Validator that checks if file path is present and reasonable."""

    def validator(output):
        if "File Path:" not in output:
            # File path might be optional
            return True, "File path not present (optional on some systems)"

        # Extract the path
        pattern = r"File Path:\s+(.+?)(?:\n|$)"
        match = re.search(pattern, output)
        if not match:
            return False, "Could not extract file path"

        path = match.group(1).strip()

        # Verify path looks reasonable (should be in /System or similar)
        if not path.startswith("/"):
            return False, f"File path doesn't start with /: {path}"

        # Common locations for shared cache
        valid_prefixes = ["/System/", "/private/var/"]
        if not any(path.startswith(prefix) for prefix in valid_prefixes):
            # Still valid, but unexpected
            pass

        return True, f"Valid file path: {path}"

    return validator


def validate_verbose_output():
    """Validator that checks for verbose debug output."""

    def validator(output):
        # In verbose mode, we expect either debug output or the normal output
        if "[DEBUG]" in output:
            return True, "Verbose debug output present"

        # If no debug output, at least check normal output is there
        if "Dyld Shared Cache Information" in output and "Base Address:" in output:
            return True, "Normal output present (debug may not show in all cases)"

        if "error" in output.lower():
            return False, f"Error in output: {output[:300]}"

        return False, f"Unexpected verbose output: {output[:300]}"

    return validator


def validate_cache_not_available():
    """Validator that handles cases where shared cache is not available."""

    def validator(output):
        # Some processes might not use shared cache
        if "No shared cache" in output or "not available" in output.lower():
            return True, "Correctly reported no shared cache"

        # Or it might have succeeded
        if "Dyld Shared Cache Information" in output and "Base Address:" in output:
            return True, "Shared cache info displayed"

        return False, f"Unexpected output: {output[:300]}"

    return validator


def combine_validators(*validators):
    """Combine multiple validators - all must pass."""

    def validator(output):
        for v in validators:
            passed, msg = v(output)
            if not passed:
                return False, msg
        return True, "All validations passed"

    return validator


# =============================================================================
# Test Specs
# =============================================================================


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Test 1: Basic shared cache info
        (
            "Display shared cache info",
            ["osc"],
            validate_shared_cache_info(),
        ),
        # Test 2: Validate addresses are correct and consistent
        (
            "Verify cache addresses are valid",
            ["osc"],
            validate_cache_addresses(),
        ),
        # Test 3: Validate cache slide (ASLR)
        (
            "Verify cache slide is valid",
            ["osc"],
            validate_cache_slide(),
        ),
        # Test 4: Validate UUID format
        (
            "Verify UUID format is correct",
            ["osc"],
            validate_uuid_format(),
        ),
        # Test 5: Validate file path
        (
            "Verify file path is present",
            ["osc"],
            validate_file_path(),
        ),
        # Test 6: Comprehensive validation
        (
            "Verify all fields together",
            ["osc"],
            combine_validators(
                validate_shared_cache_info(),
                validate_cache_addresses(),
                validate_cache_slide(),
                validate_uuid_format(),
                validate_file_path(),
            ),
        ),
        # Test 7: Verbose mode
        (
            "Display with verbose output",
            ["osc --verbose"],
            validate_verbose_output(),
        ),
        # Test 8: Short verbose flag
        (
            "Display with -v flag",
            ["osc -v"],
            validate_verbose_output(),
        ),
        # Test 9: Verbose mode with full validation
        (
            "Verify verbose output with valid addresses",
            ["osc --verbose"],
            combine_validators(
                validate_cache_addresses(),
                validate_cache_slide(),
            ),
        ),
    ]


# =============================================================================
# Main
# =============================================================================


def main():
    """Run all osc tests."""
    test_specs = get_test_specs()

    passed, total, elapsed, results = run_shared_test_suite(
        "osc tests",
        test_specs,
        scripts=["scripts"],  # Load the whole package
    )

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
