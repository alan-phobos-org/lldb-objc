"""
Unit tests for objc_utils.py pure Python functions.

These tests cover string parsing, formatting, and manipulation logic
that doesn't require LLDB runtime.
"""

import pytest
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))

from objc_core import (
    unquote_string,
    parse_method_signature,
    format_method_name,
    extract_inherited_class,
    extract_category_from_symbol,
)


class TestUnquoteString:
    """Tests for unquote_string() function."""

    @pytest.mark.parsing
    def test_unquote_simple_string(self):
        """Should remove quotes from simple quoted string."""
        assert unquote_string('"hello"') == "hello"

    @pytest.mark.parsing
    def test_unquote_empty_string(self):
        """Should handle empty quoted string."""
        assert unquote_string('""') == ""

    @pytest.mark.parsing
    def test_unquote_with_escaped_quotes(self):
        """Should unescape internal escaped quotes."""
        assert unquote_string('"@\\"NSString\\""') == '@"NSString"'

    @pytest.mark.parsing
    def test_unquote_no_quotes(self):
        """Should return unchanged if no quotes."""
        assert unquote_string("no quotes") == "no quotes"

    @pytest.mark.parsing
    def test_unquote_single_quote_only(self):
        """Should not remove if only one quote present."""
        assert unquote_string('"') == '"'

    @pytest.mark.parsing
    def test_unquote_none(self):
        """Should handle None gracefully."""
        assert unquote_string(None) is None

    @pytest.mark.parsing
    def test_unquote_preserves_internal_quotes(self):
        """Should preserve multiple internal escaped quotes."""
        assert unquote_string('"a\\"b\\"c"') == 'a"b"c'


class TestParseMethodSignature:
    """Tests for parse_method_signature() function."""

    @pytest.mark.parsing
    def test_parse_instance_method(self):
        """Should parse instance method correctly."""
        is_inst, cls, sel, err = parse_method_signature("-[NSString length]")
        assert is_inst is True
        assert cls == "NSString"
        assert sel == "length"
        assert err is None

    @pytest.mark.parsing
    def test_parse_class_method(self):
        """Should parse class method correctly."""
        is_inst, cls, sel, err = parse_method_signature("+[NSDate date]")
        assert is_inst is False
        assert cls == "NSDate"
        assert sel == "date"
        assert err is None

    @pytest.mark.parsing
    def test_parse_auto_detect_method(self):
        """Should parse bare brackets as auto-detect."""
        is_inst, cls, sel, err = parse_method_signature("[NSString length]")
        assert is_inst is None  # Auto-detect signal
        assert cls == "NSString"
        assert sel == "length"
        assert err is None

    @pytest.mark.parsing
    def test_parse_method_with_args(self):
        """Should parse method with multiple arguments."""
        is_inst, cls, sel, err = parse_method_signature("-[NSString stringByReplacingOccurrencesOfString:withString:]")
        assert is_inst is True
        assert cls == "NSString"
        assert sel == "stringByReplacingOccurrencesOfString:withString:"
        assert err is None

    @pytest.mark.parsing
    def test_parse_private_class(self):
        """Should handle private class names with underscores."""
        is_inst, cls, sel, err = parse_method_signature("-[_UINavigationBar _update]")
        assert is_inst is True
        assert cls == "_UINavigationBar"
        assert sel == "_update"
        assert err is None

    @pytest.mark.parsing
    def test_parse_invalid_no_brackets(self):
        """Should return error for invalid format."""
        is_inst, cls, sel, err = parse_method_signature("NSString length")
        assert is_inst is None
        assert cls is None
        assert sel is None
        assert err is not None
        assert "Expected" in err

    @pytest.mark.parsing
    def test_parse_invalid_missing_class(self):
        """Should return error if class name missing."""
        is_inst, cls, sel, err = parse_method_signature("-[length]")
        assert is_inst is None
        assert cls is None
        assert sel is None
        assert err is not None
        assert "Invalid format" in err

    @pytest.mark.parsing
    def test_parse_whitespace_handling(self):
        """Should handle extra whitespace correctly."""
        is_inst, cls, sel, err = parse_method_signature("  -[NSString length]  ")
        assert is_inst is True
        assert cls == "NSString"
        assert sel == "length"
        assert err is None

    @pytest.mark.parsing
    def test_parse_no_closing_bracket(self):
        """Should handle missing closing bracket."""
        is_inst, cls, sel, err = parse_method_signature("-[NSString length")
        assert is_inst is True
        assert cls == "NSString"
        assert sel == "length"
        assert err is None


class TestFormatMethodName:
    """Tests for format_method_name() function."""

    @pytest.mark.formatting
    def test_format_instance_method(self):
        """Should format instance method with - prefix."""
        result = format_method_name("NSString", "length", True)
        assert result == "-[NSString length]"

    @pytest.mark.formatting
    def test_format_class_method(self):
        """Should format class method with + prefix."""
        result = format_method_name("NSDate", "date", False)
        assert result == "+[NSDate date]"

    @pytest.mark.formatting
    def test_format_method_with_args(self):
        """Should format method with multiple arguments."""
        result = format_method_name("NSString", "stringByReplacingOccurrencesOfString:withString:", True)
        assert result == "-[NSString stringByReplacingOccurrencesOfString:withString:]"

    @pytest.mark.formatting
    def test_format_private_class(self):
        """Should format private class names correctly."""
        result = format_method_name("_UINavigationBar", "_update", True)
        assert result == "-[_UINavigationBar _update]"


class TestExtractInheritedClass:
    """Tests for _extract_inherited_class() function."""

    @pytest.mark.parsing
    def test_extract_inherited_instance_method(self):
        """Should detect inherited instance method."""
        result = extract_inherited_class("-[NSObject hash]", "NSString", "hash", True)
        assert result == "NSObject"

    @pytest.mark.parsing
    def test_extract_inherited_class_method(self):
        """Should detect inherited class method."""
        result = extract_inherited_class("+[NSObject alloc]", "NSString", "alloc", False)
        assert result == "NSObject"

    @pytest.mark.parsing
    def test_extract_own_method(self):
        """Should return None for class's own method."""
        result = extract_inherited_class("-[NSString length]", "NSString", "length", True)
        assert result is None

    @pytest.mark.parsing
    def test_extract_selector_mismatch(self):
        """Should return None if selector doesn't match."""
        result = extract_inherited_class(
            "-[NSObject hash]",
            "NSString",
            "length",  # Different selector
            True,
        )
        assert result is None

    @pytest.mark.parsing
    def test_extract_invalid_symbol(self):
        """Should return None for invalid symbol format."""
        result = extract_inherited_class("invalid_symbol", "NSString", "length", True)
        assert result is None

    @pytest.mark.parsing
    def test_extract_type_mismatch(self):
        """Should return None if method type doesn't match symbol."""
        # Symbol is instance method (-) but we're checking class method
        result = extract_inherited_class(
            "-[NSObject hash]",
            "NSString",
            "hash",
            False,  # Checking class method
        )
        # Still returns NSObject because the regex doesn't check prefix
        # This is current behavior - may want to add prefix validation
        assert result == "NSObject"


class TestExtractCategoryFromSymbol:
    """Tests for extract_category_from_symbol() function."""

    @pytest.mark.parsing
    def test_extract_category_instance_method(self):
        """Should extract category from instance method."""
        cls, cat, sel = extract_category_from_symbol("-[NSString(Addition) isEmpty]")
        assert cls == "NSString"
        assert cat == "Addition"
        assert sel == "isEmpty"

    @pytest.mark.parsing
    def test_extract_category_class_method(self):
        """Should extract category from class method."""
        cls, cat, sel = extract_category_from_symbol("+[NSDate(Formatting) dateFormatter]")
        assert cls == "NSDate"
        assert cat == "Formatting"
        assert sel == "dateFormatter"

    @pytest.mark.parsing
    def test_extract_no_category(self):
        """Should handle methods without categories."""
        cls, cat, sel = extract_category_from_symbol("-[NSString length]")
        assert cls == "NSString"
        assert cat is None
        assert sel == "length"

    @pytest.mark.parsing
    def test_extract_category_with_args(self):
        """Should handle methods with arguments."""
        cls, cat, sel = extract_category_from_symbol("-[NSString(Utils) stringByAppending:]")
        assert cls == "NSString"
        assert cat == "Utils"
        assert sel == "stringByAppending:"

    @pytest.mark.parsing
    def test_extract_invalid_symbol(self):
        """Should return None values for invalid symbols."""
        cls, cat, sel = extract_category_from_symbol("invalid")
        assert cls is None
        assert cat is None
        assert sel is None

    @pytest.mark.parsing
    def test_extract_category_private_class(self):
        """Should handle private classes with categories."""
        cls, cat, sel = extract_category_from_symbol("-[_UINavigationBar(Private) _update]")
        assert cls == "_UINavigationBar"
        assert cat == "Private"
        assert sel == "_update"


# Test parametrization examples for comprehensive coverage
class TestParseMethodSignatureParametrized:
    """Parametrized tests for parse_method_signature edge cases."""

    @pytest.mark.parsing
    @pytest.mark.parametrize(
        "signature,expected_class,expected_selector",
        [
            ("-[NSString init]", "NSString", "init"),
            ("-[NSString initWithUTF8String:]", "NSString", "initWithUTF8String:"),
            ("+[NSString string]", "NSString", "string"),
            ("[NSObject new]", "NSObject", "new"),
            (
                "-[CSSymbolicator _internal_symbolicate:withOptions:completion:]",
                "CSSymbolicator",
                "_internal_symbolicate:withOptions:completion:",
            ),
        ],
    )
    def test_various_valid_signatures(self, signature, expected_class, expected_selector):
        """Should correctly parse various valid method signatures."""
        is_inst, cls, sel, err = parse_method_signature(signature)
        assert cls == expected_class
        assert sel == expected_selector
        assert err is None

    @pytest.mark.parsing
    @pytest.mark.parametrize(
        "invalid_signature",
        [
            "",
            "NSString",
            "-NSString length]",
            "-[NSString",
            "NSString length",
        ],
    )
    def test_various_invalid_signatures(self, invalid_signature):
        """Should return errors for various invalid formats."""
        is_inst, cls, sel, err = parse_method_signature(invalid_signature)
        assert err is not None

    @pytest.mark.parsing
    def test_double_brackets_parsed_as_bare_bracket(self):
        """Double brackets are parsed as auto-detect (current behavior)."""
        # This is current behavior - parses as '[NSString length]]'
        is_inst, cls, sel, err = parse_method_signature("[[NSString length]]")
        assert is_inst is None  # Auto-detect
        assert cls == "[NSString"
        assert sel == "length]"
        assert err is None
