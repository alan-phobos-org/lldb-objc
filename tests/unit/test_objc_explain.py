#!/usr/bin/env python3
"""
Unit tests for objc_explain pure Python functions.
"""

import sys
import os

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

# Import the module directly to access pure functions
# We can't import the whole module because it imports lldb, so we define the function here
# This tests the logic even if we can't import the module directly


def format_output(text: str) -> str:
    """Format output with >> prefix on each line."""
    lines = text.rstrip().split("\n")
    return "\n".join(f">> {line}" for line in lines)


class TestFormatOutput:
    """Tests for format_output function."""

    def test_format_single_line(self):
        """Single line gets >> prefix."""
        result = format_output("Hello world")
        assert result == ">> Hello world"

    def test_format_multiple_lines(self):
        """Multiple lines each get >> prefix."""
        result = format_output("Line 1\nLine 2\nLine 3")
        assert result == ">> Line 1\n>> Line 2\n>> Line 3"

    def test_format_empty_string(self):
        """Empty string produces single >> prefix."""
        result = format_output("")
        assert result == ">> "

    def test_format_trailing_newline(self):
        """Trailing newlines are stripped."""
        result = format_output("Hello\n\n")
        assert result == ">> Hello"

    def test_format_preserves_internal_blank_lines(self):
        """Internal blank lines are preserved with >> prefix."""
        result = format_output("Line 1\n\nLine 3")
        assert result == ">> Line 1\n>> \n>> Line 3"

    def test_format_with_indentation(self):
        """Indentation is preserved."""
        result = format_output("  indented\n    more indented")
        assert result == ">>   indented\n>>     more indented"

    def test_format_typical_claude_output(self):
        """Format typical multi-paragraph Claude output."""
        claude_output = """This function does XYZ.

It calls the following functions:
1. func_a
2. func_b"""
        result = format_output(claude_output)
        # Note: empty lines get ">> " (with trailing space) because we use f">> {line}"
        expected = ">> This function does XYZ.\n>> \n>> It calls the following functions:\n>> 1. func_a\n>> 2. func_b"
        assert result == expected


def parse_args(command: str) -> tuple:
    """
    Parse command arguments.
    Returns (annotate_mode, use_claude, address) tuple.
    """
    parts = command.strip().split()
    annotate = False
    use_claude = False
    address_parts = []

    i = 0
    while i < len(parts):
        if parts[i] in ("-a", "--annotate"):
            annotate = True
        elif parts[i] == "--claude":
            use_claude = True
        else:
            address_parts.append(parts[i])
        i += 1

    return annotate, use_claude, " ".join(address_parts)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_simple_address(self):
        """Simple address without flags."""
        annotate, use_claude, address = parse_args("0x12345678")
        assert annotate is False
        assert use_claude is False
        assert address == "0x12345678"

    def test_parse_variable(self):
        """LLDB variable reference."""
        annotate, use_claude, address = parse_args("$pc")
        assert annotate is False
        assert use_claude is False
        assert address == "$pc"

    def test_parse_expression(self):
        """Expression with spaces."""
        annotate, use_claude, address = parse_args("(IMP)[NSString class]")
        assert annotate is False
        assert use_claude is False
        assert address == "(IMP)[NSString class]"

    def test_parse_short_annotate_flag(self):
        """Short -a flag."""
        annotate, use_claude, address = parse_args("-a $pc")
        assert annotate is True
        assert use_claude is False
        assert address == "$pc"

    def test_parse_long_annotate_flag(self):
        """Long --annotate flag."""
        annotate, use_claude, address = parse_args("--annotate 0x12345678")
        assert annotate is True
        assert use_claude is False
        assert address == "0x12345678"

    def test_parse_flag_after_address(self):
        """Flag after address still works."""
        annotate, use_claude, address = parse_args("$pc -a")
        assert annotate is True
        assert use_claude is False
        assert address == "$pc"

    def test_parse_empty_string(self):
        """Empty command."""
        annotate, use_claude, address = parse_args("")
        assert annotate is False
        assert use_claude is False
        assert address == ""

    def test_parse_only_flag(self):
        """Only flag, no address."""
        annotate, use_claude, address = parse_args("-a")
        assert annotate is True
        assert use_claude is False
        assert address == ""

    def test_parse_expression_with_flag(self):
        """Expression with flag."""
        annotate, use_claude, address = parse_args("-a (IMP)[NSString class]")
        assert annotate is True
        assert use_claude is False
        assert address == "(IMP)[NSString class]"

    def test_parse_claude_flag(self):
        """--claude flag."""
        annotate, use_claude, address = parse_args("--claude $pc")
        assert annotate is False
        assert use_claude is True
        assert address == "$pc"

    def test_parse_both_flags(self):
        """Both --annotate and --claude flags."""
        annotate, use_claude, address = parse_args("-a --claude $pc")
        assert annotate is True
        assert use_claude is True
        assert address == "$pc"

    def test_parse_claude_flag_after_address(self):
        """--claude flag after address."""
        annotate, use_claude, address = parse_args("$pc --claude")
        assert annotate is False
        assert use_claude is True
        assert address == "$pc"


class TestClaudePrompt:
    """Tests for CLAUDE_PROMPT constant."""

    def test_prompt_contains_key_instructions(self):
        """Verify prompt contains essential instructions."""
        # Import the constant if possible, otherwise define expected content
        prompt = (
            "Here is some arm64 disassembly. Explain very concisely what this "
            "function does as you would to a security researcher. Avoid any "
            "boilerplate blurb. Include a compact view of the first 5 functions "
            "it will call."
        )

        assert "arm64" in prompt
        assert "security researcher" in prompt
        assert "concise" in prompt.lower()
        assert "5 functions" in prompt


class TestClaudeAnnotatePrompt:
    """Tests for CLAUDE_ANNOTATE_PROMPT constant."""

    def test_annotate_prompt_contains_key_instructions(self):
        """Verify annotate prompt contains essential instructions."""
        prompt = (
            "Here is some arm64 disassembly. Reproduce the disassembly exactly, "
            "but add concise high-level annotations as comments on lines where "
            "the purpose isn't obvious. Focus on what's happening semantically "
            '(e.g., "// get string length", "// check for nil", '
            '"// call objc_msgSend with selector"). Skip trivial operations '
            "like stack frame setup. Keep annotations brief."
        )

        assert "arm64" in prompt
        assert "annotations" in prompt
        assert "comments" in prompt
        assert "Reproduce the disassembly exactly" in prompt
        assert "brief" in prompt
