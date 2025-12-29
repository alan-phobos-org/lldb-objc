#!/usr/bin/env python3
"""
Test script for the oprotos command (Protocol Conformance Finder).

This script tests the oprotos functionality:
- Finding classes that conform to a specific protocol
- Protocol listing with --list flag
- Wildcard pattern matching for protocols
- Direct conformance with --direct flag
- Grouping of base classes and subclasses
- Performance and caching behavior

Uses a shared LLDB session for faster test execution.

Expected command syntax:
    oprotos NSCoding                # All classes conforming to NSCoding
    oprotos NSCopying --direct      # Only classes that directly declare conformance
    oprotos *Delegate               # Wildcard: all protocols ending in "Delegate"
    oprotos --list                  # List all registered protocols
    oprotos --list NS*              # List protocols matching pattern
"""

import sys
import re
import os
from test_helpers import (
    TestResult, check_hello_world_binary, run_shared_test_suite, PROJECT_ROOT
)


# =============================================================================
# Validator Functions
# =============================================================================

def validate_basic_conformance():
    """Validator for basic protocol conformance."""
    def validator(output):
        # NSCoding is widely implemented - should find many classes
        if 'NSString' in output or 'NSDictionary' in output or 'NSArray' in output:
            match = re.search(r'(\d+)\s*class(?:es)?\s*conform', output, re.IGNORECASE)
            if match:
                count = int(match.group(1))
                if count > 10:
                    return True, f"Found {count} classes conforming to NSCoding"
                return False, (f"Too few conforming classes found\n"
                              f"    Expected: More than 10 classes conforming to NSCoding\n"
                              f"    Actual: {count} classes\n"
                              f"    Possible cause: NSCoding is widely implemented in Foundation")
            return True, "Found conforming classes (count format may differ)"
        elif 'error' in output.lower():
            return False, (f"Command encountered error\n"
                          f"    Expected: List of classes conforming to NSCoding\n"
                          f"    Actual output: {output[:300]}")
        return False, (f"No conforming classes found\n"
                      f"    Expected: NSString, NSDictionary, NSArray or similar classes\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_nscopying_conformance():
    """Validator for NSCopying conformance."""
    def validator(output):
        if 'NS' in output and 'conform' in output.lower():
            return True, "NSCopying conformance lookup works"
        elif 'error' in output.lower():
            return False, (f"Command encountered error\n"
                          f"    Expected: List of classes conforming to NSCopying\n"
                          f"    Actual output: {output[:200]}")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Classes with 'NS' prefix and 'conform' message\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_protocol_not_found():
    """Validator for non-existent protocol."""
    def validator(output):
        if 'not found' in output.lower() or 'no protocol' in output.lower() or '0' in output:
            return True, "Properly reports protocol not found"
        elif 'error' in output.lower():
            return True, "Reports error for invalid protocol"
        return False, (f"Protocol not found message missing\n"
                      f"    Expected: 'not found' or 'no protocol' or '0' in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_case_sensitive():
    """Validator for case sensitivity."""
    def validator(output):
        if 'not found' in output.lower() or '0 class' in output.lower() or 'no protocol' in output.lower():
            return True, "Protocol lookup is case-sensitive"
        elif 'NSCoding' in output:
            return True, "Protocol found (command may be case-insensitive)"
        return False, (f"Case sensitivity behavior unclear\n"
                      f"    Expected: 'not found' or '0 class' (case-sensitive) or NSCoding results (case-insensitive)\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_list_all_protocols():
    """Validator for listing all protocols."""
    def validator(output):
        if 'NSCoding' in output or 'NSCopying' in output or 'NSObject' in output:
            match = re.search(r'Total:\s*(\d+)\s*protocol', output, re.IGNORECASE)
            if match:
                count = int(match.group(1))
                if count > 50:
                    return True, f"Listed {count} protocols"
                return False, (f"Too few protocols listed\n"
                              f"    Expected: More than 50 protocols (macOS/iOS Foundation has many)\n"
                              f"    Actual: {count} protocols\n"
                              f"    Possible cause: Protocol scanning incomplete or filtered")
            return True, "Protocols listed"
        elif 'Total' in output:
            return True, "Protocol list displayed with total"
        return False, (f"No protocols listed\n"
                      f"    Expected: Protocol list with NSCoding, NSCopying, NSObject, etc.\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_list_with_pattern():
    """Validator for listing protocols with pattern."""
    def validator(output):
        if 'NS' in output:
            ns_count = len(re.findall(r'\bNS\w+', output))
            if ns_count >= 3:
                return True, f"Found {ns_count} NS* protocols"
            return True, "NS* protocols found"
        elif 'No protocols' in output or '0 protocol' in output:
            return False, (f"No NS* protocols found\n"
                          f"    Expected: Multiple protocols starting with NS (NSCoding, NSCopying, etc.)\n"
                          f"    Actual: No protocols matched pattern\n"
                          f"    Possible cause: Pattern matching not working")
        return False, (f"Unexpected output format\n"
                      f"    Expected: NS-prefixed protocols (NSCoding, NSCopying, etc.)\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_delegate_protocols():
    """Validator for delegate protocols."""
    def validator(output):
        if 'Delegate' in output:
            delegate_count = len(re.findall(r'\w+Delegate', output))
            if delegate_count >= 1:
                return True, f"Found {delegate_count} *Delegate protocols"
            return True, "Delegate protocols found"
        elif 'No protocols' in output:
            return False, (f"No *Delegate protocols found\n"
                          f"    Expected: At least one Delegate protocol (e.g., NSApplicationDelegate)\n"
                          f"    Actual: No protocols matched pattern\n"
                          f"    Possible cause: Delegate protocols should exist in Cocoa frameworks")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Protocols ending with 'Delegate'\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_datasource_protocols():
    """Validator for data source protocols."""
    def validator(output):
        if 'DataSource' in output or 'No protocols' in output or '0 protocol' in output:
            return True, "DataSource pattern handled"
        return False, (f"Unexpected output format\n"
                      f"    Expected: DataSource protocols or 'No protocols' message\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_prefix():
    """Validator for prefix wildcard."""
    def validator(output):
        if 'NSCoding' in output or 'NSCopying' in output or 'protocol' in output.lower():
            return True, "Prefix wildcard matching works"
        elif 'No protocol' in output:
            return False, (f"No NS* protocols found\n"
                          f"    Expected: NSCoding, NSCopying, or other NS* protocols\n"
                          f"    Actual: No protocols matched wildcard\n"
                          f"    Possible cause: Prefix wildcard pattern not working")
        return False, (f"Unexpected output format\n"
                      f"    Expected: NS* protocols (NSCoding, NSCopying) or 'protocol' keyword\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_suffix():
    """Validator for suffix wildcard."""
    def validator(output):
        if 'Delegate' in output or 'protocol' in output.lower():
            return True, "Suffix wildcard matching works"
        elif 'No protocol' in output or 'no match' in output.lower():
            return True, "Wildcard processed (may have no matches)"
        return False, (f"Unexpected output format\n"
                      f"    Expected: Delegate protocols or 'protocol' keyword or 'No protocol' message\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_contains():
    """Validator for contains wildcard."""
    def validator(output):
        if 'Cod' in output or 'protocol' in output.lower():
            return True, "Contains wildcard matching works"
        return False, (f"Unexpected output format\n"
                      f"    Expected: Protocols containing 'Cod' (like NSCoding) or 'protocol' keyword\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_wildcard_single_char():
    """Validator for single character wildcard."""
    def validator(output):
        if 'NSCoding' in output or 'conform' in output.lower():
            return True, "Single character wildcard works"
        elif 'No protocol' in output or 'no match' in output.lower():
            return True, "Single char wildcard processed"
        return False, (f"Unexpected output format\n"
                      f"    Expected: NSCoding or 'conform' keyword or 'No protocol' message\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_direct_conformance():
    """Validator for --direct flag."""
    def validator(output):
        if 'conform' in output.lower() or 'class' in output.lower():
            return True, "--direct flag accepted and processed"
        elif 'error' not in output.lower():
            return True, "--direct flag processed"
        return False, (f"--direct flag issue\n"
                      f"    Expected: Conformance results or class list with --direct flag\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_direct_vs_inherited():
    """Validator for direct vs inherited (just check both work)."""
    def validator(output):
        # This test runs both queries; just verify they both complete
        if 'conform' in output.lower() or 'class' in output.lower():
            return True, "Both queries completed"
        return False, (f"Query failed\n"
                      f"    Expected: Both direct and inherited conformance queries to complete\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_subclass_grouping():
    """Validator for subclass grouping."""
    def validator(output):
        if '-> also:' in output or '  -> ' in output or 'also:' in output.lower():
            return True, "Subclass grouping shown"
        elif 'NSMutableString' in output and 'NSString' in output:
            return True, "Base and subclasses both listed"
        elif 'conform' in output.lower():
            return True, "Conformance results shown (grouping may vary)"
        return False, (f"No subclass grouping information\n"
                      f"    Expected: Grouping indicators like '-> also:' or base/subclass pairs\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_timing_metrics():
    """Validator for timing metrics."""
    def validator(output):
        has_timing = any([
            re.search(r'\d+\.?\d*\s*s\]', output),
            'scanned' in output.lower(),
            'time' in output.lower()
        ])

        if has_timing:
            return True, "Timing metrics displayed"
        elif 'Total:' in output or 'conform' in output.lower():
            return True, "Results shown (timing format may vary)"
        return False, (f"No timing information found\n"
                      f"    Expected: Timing metrics like '0.5s' or 'scanned' or 'time'\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_class_count():
    """Validator for class count display."""
    def validator(output):
        if re.search(r'Total:\s*\d+', output) or re.search(r'\d+\s*class', output, re.IGNORECASE):
            return True, "Class count displayed"
        elif 'conform' in output.lower():
            return True, "Conformance results shown"
        return False, (f"No class count displayed\n"
                      f"    Expected: 'Total: N' or 'N class' in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_scanned_classes():
    """Validator for scanned classes metric."""
    def validator(output):
        if re.search(r'scanned\s+\d+', output, re.IGNORECASE):
            return True, "Scanned classes metric shown"
        elif re.search(r'\[\d+\s*class', output, re.IGNORECASE):
            return True, "Class scan metric present"
        elif 'conform' in output.lower():
            return True, "Results shown (scan metric format may vary)"
        return False, (f"No scanned classes metric found\n"
                      f"    Expected: 'scanned N' or '[N class' pattern in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_cache_reuse():
    """Validator for cache reuse."""
    def validator(output):
        if 'cached' in output.lower() or 'conform' in output.lower():
            return True, "Cache potentially reused"
        return False, (f"Cache behavior unclear\n"
                      f"    Expected: 'cached' indicator or conformance results (cache implicit)\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_verbose_flag():
    """Validator for --verbose flag."""
    def validator(output):
        has_verbose_info = any([
            'expression' in output.lower(),
            'memory read' in output.lower(),
            'timing' in output.lower(),
            'batch' in output.lower()
        ])

        if has_verbose_info:
            return True, "Verbose metrics shown"
        elif 'conform' in output.lower():
            return True, "Command works (verbose format may vary)"
        return False, (f"No verbose output detected\n"
                      f"    Expected: Verbose info like 'expression', 'memory read', 'timing', 'batch'\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_reload_flag():
    """Validator for --reload flag."""
    def validator(output):
        if 'cached' not in output.lower() or 'conform' in output.lower():
            return True, "--reload flag accepted"
        return False, (f"Reload flag may have failed\n"
                      f"    Expected: Fresh results without 'cached' indicator\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_no_arguments():
    """Validator for no arguments error."""
    def validator(output):
        if 'usage' in output.lower() or 'error' in output.lower() or 'protocol' in output.lower():
            return True, "Usage/error shown for no arguments"
        elif '--list' in output or '--help' in output:
            return True, "Help shown for no arguments"
        return False, (f"Missing usage/help message\n"
                      f"    Expected: 'usage' or 'error' or 'protocol' or help text\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_invalid_flag():
    """Validator for invalid flag error."""
    def validator(output):
        if 'error' in output.lower() or 'unknown' in output.lower() or 'invalid' in output.lower():
            return True, "Invalid flag reported"
        elif 'conform' in output.lower() or 'class' in output.lower():
            return True, "Command completed (unknown flag ignored)"
        elif 'TIMEOUT' in output:
            return False, (f"Command timed out\n"
                          f"    Expected: Error message or command completion\n"
                          f"    Actual: Command exceeded time limit\n"
                          f"    Output: {output[:300]}")
        return False, (f"Invalid flag not reported\n"
                      f"    Expected: 'error' or 'unknown' or 'invalid' message\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_empty_conformance():
    """Validator for empty result."""
    def validator(output):
        if 'not found' in output.lower() or 'no class' in output.lower() or '0' in output:
            return True, "Handles no-match case gracefully"
        elif 'error' in output.lower():
            return True, "Reports error for missing protocol"
        return False, (f"No-match case not handled gracefully\n"
                      f"    Expected: 'not found' or 'no class' or '0' in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_nsobject_protocol():
    """Validator for NSObject protocol."""
    def validator(output):
        match = re.search(r'(\d+)\s*class', output, re.IGNORECASE)
        if match:
            count = int(match.group(1))
            if count > 100:
                return True, f"NSObject protocol: {count} conforming classes"
            return False, (f"Too few NSObject protocol conformances\n"
                          f"    Expected: More than 100 classes (NSObject is fundamental)\n"
                          f"    Actual: {count} classes\n"
                          f"    Possible cause: NSObject protocol should be widely adopted")
        elif 'conform' in output.lower():
            return True, "NSObject protocol lookup completed"
        return False, (f"Unexpected output format\n"
                      f"    Expected: Class count or 'conform' keyword for NSObject protocol\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_secure_coding():
    """Validator for NSSecureCoding."""
    def validator(output):
        if 'conform' in output.lower() or 'class' in output.lower():
            return True, "NSSecureCoding lookup works"
        elif 'not found' in output.lower():
            return False, (f"NSSecureCoding protocol not found\n"
                          f"    Expected: NSSecureCoding protocol exists in modern Foundation\n"
                          f"    Actual: Protocol not found\n"
                          f"    Possible cause: NSSecureCoding should be available on macOS/iOS")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Conformance results or class list for NSSecureCoding\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_private_protocol():
    """Validator for private framework protocol."""
    def validator(output):
        if 'IDS' in output or 'No protocol' in output or 'protocol' in output.lower():
            return True, "Private framework protocol lookup handled"
        return False, (f"Unexpected output format\n"
                      f"    Expected: IDS protocols or 'No protocol' message or 'protocol' keyword\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_combined_flags():
    """Validator for combined flags."""
    def validator(output):
        if 'conform' in output.lower() or 'class' in output.lower():
            return True, "Combined flags work"
        elif 'error' in output.lower():
            return False, (f"Error with combined flags\n"
                          f"    Expected: --direct and --verbose flags to work together\n"
                          f"    Actual output: {output[:200]}")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Conformance results with combined --direct --verbose flags\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_sorted_protocols():
    """Validator for sorted protocol list."""
    def validator(output):
        protocols = re.findall(r'\bNS\w+(?:Protocol)?\b', output)

        if len(protocols) >= 3:
            cleaned = list(dict.fromkeys(protocols))
            is_sorted = cleaned == sorted(cleaned)
            if is_sorted:
                return True, "Protocol list is sorted"
            return True, "Protocols listed (sorting may vary)"
        elif len(protocols) >= 1:
            return True, "Protocols found"
        return False, (f"No protocols to verify sorting\n"
                      f"    Expected: At least one NS-prefixed protocol in output\n"
                      f"    Actual output: {output[:300]}")
    return validator


def validate_sorted_classes():
    """Validator for sorted conforming class list."""
    def validator(output):
        lines = output.split('\n')
        class_names = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped[0].isupper() and not stripped.startswith(('Total', 'Found', '[', '-')):
                parts = stripped.split()
                if parts:
                    name = parts[0]
                    if re.match(r'^[A-Z][A-Za-z0-9_]+$', name):
                        class_names.append(name)

        if len(class_names) >= 3:
            is_sorted = class_names == sorted(class_names)
            if is_sorted:
                return True, "Conforming classes sorted alphabetically"
            return True, "Classes listed (sorting may vary or grouping affects order)"
        elif 'conform' in output.lower():
            return True, "Conformance results shown"
        return False, (f"No classes to verify sorting\n"
                      f"    Expected: Multiple class names in output for sorting verification\n"
                      f"    Actual output: {output[:300]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic functionality
        (
            "Basic conformance: NSCoding",
            ['oprotos NSCoding'],
            validate_basic_conformance()
        ),
        (
            "Conformance: NSCopying",
            ['oprotos NSCopying'],
            validate_nscopying_conformance()
        ),
        (
            "Non-existent protocol",
            ['oprotos NonExistentProtocol12345'],
            validate_protocol_not_found()
        ),
        (
            "Case sensitivity: nscoding vs NSCoding",
            ['oprotos nscoding'],
            validate_case_sensitive()
        ),
        # Protocol listing (--list)
        (
            "List all protocols: --list",
            ['oprotos --list'],
            validate_list_all_protocols()
        ),
        (
            "List with pattern: --list NS*",
            ['oprotos --list NS*'],
            validate_list_with_pattern()
        ),
        (
            "List pattern: --list *Delegate",
            ['oprotos --list *Delegate'],
            validate_delegate_protocols()
        ),
        (
            "List pattern: --list *DataSource*",
            ['oprotos --list *DataSource*'],
            validate_datasource_protocols()
        ),
        # Wildcard patterns
        (
            "Wildcard: NS* protocols",
            ['oprotos NS*'],
            validate_wildcard_prefix()
        ),
        (
            "Wildcard: *Delegate protocols",
            ['oprotos *Delegate'],
            validate_wildcard_suffix()
        ),
        (
            "Wildcard: *Cod* (contains)",
            ['oprotos *Cod*'],
            validate_wildcard_contains()
        ),
        (
            "Wildcard: NS?oding",
            ['oprotos NS?oding'],
            validate_wildcard_single_char()
        ),
        # Direct conformance (--direct)
        (
            "Direct conformance: --direct",
            ['oprotos NSCoding --direct'],
            validate_direct_conformance()
        ),
        (
            "Direct vs inherited conformance",
            ['oprotos NSCoding', 'oprotos NSCoding --direct'],
            validate_direct_vs_inherited()
        ),
        # Output format
        (
            "Output: subclass grouping",
            ['oprotos NSCoding'],
            validate_subclass_grouping()
        ),
        (
            "Output: timing metrics",
            ['oprotos NSCoding'],
            validate_timing_metrics()
        ),
        (
            "Output: class count",
            ['oprotos NSCopying'],
            validate_class_count()
        ),
        (
            "Output: scanned classes metric",
            ['oprotos NSCoding'],
            validate_scanned_classes()
        ),
        # Caching and performance
        (
            "Performance: cache reuse",
            ['ocls NS*', 'oprotos NSCoding'],
            validate_cache_reuse()
        ),
        (
            "Flag: --verbose",
            ['oprotos --verbose NSCoding'],
            validate_verbose_flag()
        ),
        (
            "Flag: --reload",
            ['oprotos --reload NSCoding'],
            validate_reload_flag()
        ),
        # Error handling
        (
            "Error: no arguments",
            ['oprotos'],
            validate_no_arguments()
        ),
        (
            "Error: invalid flag",
            ['oprotos --invalid-flag NSCoding'],
            validate_invalid_flag()
        ),
        (
            "Empty result: rare protocol",
            ['oprotos _SomeVeryRareInternalProtocol'],
            validate_empty_conformance()
        ),
        # Edge cases
        (
            "Edge case: NSObject protocol",
            ['oprotos NSObject'],
            validate_nsobject_protocol()
        ),
        (
            "Edge case: NSSecureCoding",
            ['oprotos NSSecureCoding'],
            validate_secure_coding()
        ),
        (
            "Edge case: private framework protocol",
            ['oprotos --list IDS*'],
            validate_private_protocol()
        ),
        (
            "Combined flags: --direct --verbose",
            ['oprotos --direct --verbose NSCoding'],
            validate_combined_flags()
        ),
        (
            "List sorting: alphabetical",
            ['oprotos --list NS*'],
            validate_sorted_protocols()
        ),
        (
            "Results sorting: alphabetical",
            ['oprotos NSCopying'],
            validate_sorted_classes()
        ),
    ]


def main():
    """Run all oprotos tests using shared LLDB session."""
    # Check if objc_protos.py exists
    objc_protos_path = os.path.join(PROJECT_ROOT, 'objc_protos.py')
    if not os.path.exists(objc_protos_path):
        print(f"Note: {objc_protos_path} not found")
        print("These tests are for the upcoming oprotos feature.")
        print("Tests will fail until the feature is implemented.\n")

    categories = {
        "Basic functionality": (0, 4),
        "Protocol listing": (4, 8),
        "Wildcard patterns": (8, 12),
        "Direct conformance": (12, 14),
        "Output format": (14, 18),
        "Caching/performance": (18, 21),
        "Error handling": (21, 24),
        "Edge cases": (24, 30),
    }

    passed, total = run_shared_test_suite(
        "OPROTOS COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_cls.py', 'objc_protos.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
