#!/usr/bin/env python3
"""
Test script for the ocall command (Method Caller).

This script tests the ocall functionality:
- Class method calls: ocall +[NSDate date]
- Instance method calls with address: ocall -[0x600001234560 description]
- Instance method calls with register: ocall -[$r0 uppercaseString]
- Verbose mode: ocall --verbose +[NSDate date]

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
import os
from test_helpers import run_shared_test_suite, PROJECT_ROOT


# =============================================================================
# Validator Functions
# =============================================================================


def validate_class_method_basic():
    """Validator for basic class method call."""

    def validator(output):
        # NSDate date returns a date representation
        if re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|NSDate", output):
            return True, "Returned date value"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Command failed\n"
                f"    Expected: Date representation (YYYY-MM-DD or HH:MM:SS)\n"
                f"    Actual: Error or failure encountered\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"Unexpected output\n"
            f"    Expected: Date format or 'NSDate' in output\n"
            f"    Actual: No date representation found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_class_method_with_arg():
    """Validator for class method with string argument."""

    def validator(output):
        if "hello" in output:
            return True, "Returned string value"
        elif "error" in output.lower() and "not implemented" not in output.lower():
            return False, (
                f"Command failed\n"
                f"    Expected: String 'hello' in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"String not found in output\n"
            f"    Expected: 'hello' in returned string\n"
            f"    Actual: String not present\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_instance_method_from_variable():
    """Validator for instance method using $variable."""

    def validator(output):
        if "TestString" in output:
            return True, "Returned instance description"
        elif "error" in output.lower() and "not implemented" not in output.lower():
            return False, (
                f"Command failed\n"
                f"    Expected: 'TestString' in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"Instance description not found\n"
            f"    Expected: 'TestString' from $testStr description\n"
            f"    Actual: String not present in output\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_instance_method_from_register():
    """Validator for instance method using register."""

    def validator(output):
        # Register-based calls depend on runtime state, so be lenient
        if "description" in output.lower() or "$x0" in output or "register" in output.lower():
            return True, "Register syntax handled"
        elif "parse" in output.lower() or "syntax" in output.lower():
            return False, (
                f"Failed to parse register syntax\n"
                f"    Expected: Register syntax like '$x0' to be accepted\n"
                f"    Actual: Parse or syntax error\n"
                f"    Output preview: {output[:200]}"
            )
        # If it executed without syntax error, that's acceptable
        return True, "Command executed (result depends on register state)"

    return validator


def validate_verbose_mode():
    """Validator for verbose mode output."""

    def validator(output):
        if "Class" in output or "SEL" in output or "resolve" in output.lower():
            return True, "Shows resolution details"
        elif re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", output):
            return False, (
                f"Got result but no verbose output\n"
                f"    Expected: Resolution details ('Class', 'SEL', or 'resolve')\n"
                f"    Actual: Result returned but no verbose information\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"No resolution info\n"
            f"    Expected: Verbose output with 'Class', 'SEL', or resolution info\n"
            f"    Actual: No resolution details found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_private_class():
    """Validator for private class method call."""

    def validator(output):
        if "CSSymbolicator" in output or "0x" in output:
            return True, "Resolved private class"
        elif "not found" in output.lower():
            # Private framework classes may not be available on all macOS versions
            return True, "SKIPPED: Private class not available (expected on some macOS versions)"
        return False, (
            f"Unexpected output for private class\n"
            f"    Expected: 'CSSymbolicator' or hex address in output\n"
            f"    Actual: Neither found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_invalid_class():
    """Validator for non-existent class error."""

    def validator(output):
        if "not found" in output.lower() or "error" in output.lower() or "failed" in output.lower():
            return True, "Properly reports error for invalid class"
        return False, (
            f"Should report error for invalid class\n"
            f"    Expected: 'not found', 'error', or 'failed' message\n"
            f"    Actual: No error message found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_invalid_syntax():
    """Validator for syntax errors."""

    def validator(output):
        if "usage" in output.lower() or "syntax" in output.lower() or "error" in output.lower():
            return True, "Properly reports syntax error"
        return False, (
            f"Should report syntax error\n"
            f"    Expected: 'usage', 'syntax', or 'error' message\n"
            f"    Actual: No error message found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_return_value():
    """Validator for return value display."""

    def validator(output):
        if "42" in output:
            return True, "Shows return value"
        return False, (
            f"Return value not visible\n"
            f"    Expected: '42' in output from numberWithInt:42\n"
            f"    Actual: Value not found\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_address_prefix():
    """Validator for address prefix in output with variable name."""

    def validator(output):
        # Look for the call-style format: (Type *) $N = 0x...
        # Pattern: ($N) followed by = and hex address
        var_match = re.search(r"\$\d+\s*=\s*(0x[0-9a-fA-F]+)", output, re.MULTILINE)
        if not var_match:
            return False, (
                f"No variable assignment with address found\n"
                f"    Expected: Output like '(Type) $N = 0x...' format\n"
                f"    Actual: No matching pattern found\n"
                f"    Output preview: {output[:300]}"
            )
        return True, f"Found variable with address: {var_match.group(1)}"

    return validator


def validate_address_matches_po():
    """Validator that extracts address from ocall output and verifies it matches po output."""

    def validator(output):
        # The output contains both the ocall result and the po result
        # Look for the call-style format: (Type *) $N = 0x...
        var_match = re.search(r"\$\d+\s*=\s*(0x[0-9a-fA-F]+)", output, re.MULTILINE)
        if not var_match:
            return False, (
                f"No variable assignment with address found\n"
                f"    Expected: Output like '(Type) $N = 0x...' format\n"
                f"    Actual: No matching pattern found\n"
                f"    Output preview: {output[:300]}"
            )

        address = var_match.group(1)

        # Look for a date pattern in the output - it should appear in both ocall and po results
        # The date format from NSDate is like: 2025-12-29 21:46:51 +0000
        date_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        date_matches = re.findall(date_pattern, output)

        if len(date_matches) < 2:
            return False, (
                f"Expected two date representations (ocall and po)\n"
                f"    Found: {len(date_matches)} date(s)\n"
                f"    Address: {address}\n"
                f"    Output preview: {output[:400]}"
            )

        # Both dates should match (they're the same object)
        if date_matches[0] == date_matches[1]:
            return True, f"Address {address} verified: both show '{date_matches[0]}'"

        return False, (
            f"Date mismatch between ocall and po\n"
            f"    ocall date: {date_matches[0]}\n"
            f"    po date: {date_matches[1]}\n"
            f"    Address: {address}"
        )

    return validator


def validate_auto_detect_class_method():
    """Validator for auto-detect class method (without + prefix)."""

    def validator(output):
        # Should return a date just like +[NSDate date]
        if re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|NSDate", output):
            return True, "Auto-detected class method returned date"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Auto-detect failed\n"
                f"    Expected: Date representation\n"
                f"    Actual: Error or failure\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"Unexpected output\n    Expected: Date format from [NSDate date]\n    Output preview: {output[:200]}"
        )

    return validator


def validate_auto_detect_instance_method():
    """Validator for auto-detect instance method on variable."""

    def validator(output):
        if "AutoDetectTest" in output:
            return True, "Auto-detected instance method returned description"
        elif "error" in output.lower():
            return False, (
                f"Auto-detect instance method failed\n"
                f"    Expected: 'AutoDetectTest' in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:200]}"
            )
        return False, (
            f"Instance description not found\n"
            f"    Expected: 'AutoDetectTest' from description\n"
            f"    Output preview: {output[:200]}"
        )

    return validator


def validate_variable_name_in_output():
    """Validator that output includes variable name like $N."""

    def validator(output):
        # Look for pattern like ($N) = in the output
        if re.search(r"\$\d+\s*=", output):
            return True, "Variable name found in output"
        return False, (
            f"Variable name not found\n"
            f"    Expected: '$N =' pattern in output\n"
            f"    Actual: No variable name pattern found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


# =============================================================================
# Expression Evaluation Validators
# =============================================================================


def validate_string_literal():
    """Validator for Objective-C string literal evaluation."""

    def validator(output):
        # Should return NSTaggedPointerString or NSString with the literal value
        if "Test" in output and (
            "NSTaggedPointerString" in output or "NSString" in output or "__NSCFConstantString" in output
        ):
            return True, "String literal evaluated correctly"
        elif "Test" in output and "0x" in output:
            # Got the string value with an address - good enough
            return True, "String literal returned with address"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Expression evaluation failed\n"
                f"    Expected: 'Test' string with NSString type\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"String literal not properly evaluated\n"
            f"    Expected: 'Test' and NSString/NSTaggedPointerString in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_number_literal():
    """Validator for NSNumber literal evaluation."""

    def validator(output):
        # Should return NSNumber with the value 42
        if "42" in output and ("NSNumber" in output or "__NSCFNumber" in output or "0x" in output):
            return True, "Number literal evaluated correctly"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Number literal evaluation failed\n"
                f"    Expected: NSNumber with value 42\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Number literal not properly evaluated\n"
            f"    Expected: '42' in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_array_literal():
    """Validator for NSArray literal evaluation."""

    def validator(output):
        # Should return an NSArray with elements
        if ("NSArray" in output or "__NSArrayI" in output or "__NSArray" in output) and "0x" in output:
            return True, "Array literal evaluated correctly"
        elif "one" in output.lower() and "two" in output.lower():
            # Array contents visible
            return True, "Array literal with contents visible"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Array literal evaluation failed\n"
                f"    Expected: NSArray in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Array literal not properly evaluated\n"
            f"    Expected: NSArray type or array contents in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_dictionary_literal():
    """Validator for NSDictionary literal evaluation."""

    def validator(output):
        # Should return an NSDictionary
        if ("NSDictionary" in output or "__NSDictionary" in output) and "0x" in output:
            return True, "Dictionary literal evaluated correctly"
        elif "key" in output.lower() and "value" in output.lower():
            # Dictionary contents visible
            return True, "Dictionary literal with contents visible"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Dictionary literal evaluation failed\n"
                f"    Expected: NSDictionary in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Dictionary literal not properly evaluated\n"
            f"    Expected: NSDictionary type or dictionary contents in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_boxed_expression():
    """Validator for boxed expression evaluation like @(1+1)."""

    def validator(output):
        # Should return NSNumber with value 2
        if "2" in output and ("NSNumber" in output or "__NSCFNumber" in output or "0x" in output):
            return True, "Boxed expression evaluated correctly"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Boxed expression evaluation failed\n"
                f"    Expected: NSNumber with value 2\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Boxed expression not properly evaluated\n"
            f"    Expected: '2' in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_nested_expression():
    """Validator for nested message send expression."""

    def validator(output):
        # [[NSDate date] description] should return a date string
        if re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", output):
            return True, "Nested expression evaluated correctly"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"Nested expression evaluation failed\n"
                f"    Expected: Date string in output\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Nested expression not properly evaluated\n"
            f"    Expected: Date string in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_c_function_call():
    """Validator for C function call within expression."""

    def validator(output):
        # NSHomeDirectory() should return a path string
        if "/Users/" in output or "/var/" in output or "/home/" in output:
            return True, "C function call evaluated correctly"
        elif "error" in output.lower() or "failed" in output.lower():
            return False, (
                f"C function call evaluation failed\n"
                f"    Expected: Home directory path\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"C function call not properly evaluated\n"
            f"    Expected: Path string in output\n"
            f"    Actual: Not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


# =============================================================================
# Test Specifications
# =============================================================================


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic class methods
        (
            "Class method: +[NSDate date]",
            ["ocall +[NSDate date]"],
            validate_class_method_basic(),
        ),
        (
            "Class method with arg: +[NSString stringWithString:]",
            ['ocall +[NSString stringWithString:@"hello"]'],
            validate_class_method_with_arg(),
        ),
        # Instance methods
        (
            "Instance method from variable",
            [
                'expr NSString *$testStr = @"TestString"',
                "ocall -[$testStr description]",
            ],
            validate_instance_method_from_variable(),
        ),
        (
            "Instance method from register ($x0)",
            ["ocall -[$x0 description]"],
            validate_instance_method_from_register(),
        ),
        # Verbose mode
        (
            "Verbose mode: --verbose flag",
            ["ocall --verbose +[NSDate date]"],
            validate_verbose_mode(),
        ),
        # Private classes
        (
            "Private class: +[CSSymbolicator class]",
            ["ocall +[CSSymbolicator class]"],
            validate_private_class(),
        ),
        # Error handling
        (
            "Error: invalid class",
            ["ocall +[NonExistentClass123 someMethod]"],
            validate_invalid_class(),
        ),
        (
            "Error: invalid syntax",
            ["ocall invalid syntax here"],
            validate_invalid_syntax(),
        ),
        # Return values
        (
            "Return value display",
            ["ocall +[NSNumber numberWithInt:42]"],
            validate_return_value(),
        ),
        # Address prefix in output
        (
            "Address prefix: output starts with hex address",
            ["ocall +[NSDate date]"],
            validate_address_prefix(),
        ),
        (
            "Address prefix: po on address matches ocall description",
            [
                "expr NSDate *$testDate = [NSDate date]",
                "ocall -[$testDate description]",
                "po $testDate",
            ],
            validate_address_matches_po(),
        ),
        # Auto-detect method type
        (
            "Auto-detect: class method [NSDate date]",
            ["ocall [NSDate date]"],
            validate_auto_detect_class_method(),
        ),
        (
            "Auto-detect: instance method on $variable",
            [
                'expr NSString *$autoStr = @"AutoDetectTest"',
                "ocall [$autoStr description]",
            ],
            validate_auto_detect_instance_method(),
        ),
        # Variable name in output
        (
            "Output format: includes variable name $N",
            ["ocall +[NSDate date]"],
            validate_variable_name_in_output(),
        ),
        # Expression evaluation (arbitrary Objective-C expressions)
        (
            'Expression: string literal @"Test"',
            ['ocall @"Test"'],
            validate_string_literal(),
        ),
        ("Expression: NSNumber literal @42", ["ocall @42"], validate_number_literal()),
        (
            'Expression: NSArray literal @[@"one", @"two"]',
            ['ocall @[@"one", @"two"]'],
            validate_array_literal(),
        ),
        (
            'Expression: NSDictionary literal @{@"key": @"value"}',
            ['ocall @{@"key": @"value"}'],
            validate_dictionary_literal(),
        ),
        (
            "Expression: boxed expression @(1+1)",
            ["ocall @(1+1)"],
            validate_boxed_expression(),
        ),
        (
            "Expression: nested message send [[NSDate date] description]",
            ["ocall [[NSDate date] description]"],
            validate_nested_expression(),
        ),
        (
            "Expression: C function call NSHomeDirectory()",
            ["ocall NSHomeDirectory()"],
            validate_c_function_call(),
        ),
    ]


def main():
    """Run all ocall tests using shared LLDB session."""
    # Check if objc_call.py exists
    objc_call_path = os.path.join(PROJECT_ROOT, "objc_call.py")
    if not os.path.exists(objc_call_path):
        print(f"Note: {objc_call_path} not found")
        print("These tests are for the upcoming ocall feature.")
        print("Tests will fail until the feature is implemented.\n")

    categories = {
        "Basic class methods": (0, 2),
        "Instance methods": (2, 4),
        "Verbose mode": (4, 5),
        "Private classes": (5, 6),
        "Error handling": (6, 8),
        "Return values": (8, 9),
        "Address prefix": (9, 11),
        "Auto-detect": (11, 13),
        "Output format": (13, 14),
        "Expression evaluation": (14, 21),
    }

    passed, total = run_shared_test_suite(
        "OCALL COMMAND TEST SUITE",
        get_test_specs(),
        scripts=["scripts/objc_call.py"],
        show_category_summary=categories,
    )
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
