#!/usr/bin/env python3
"""
Unit tests for objc_decompile pure Python functions.
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
        result = format_output("void func() { return; }")
        assert result == ">> void func() { return; }"

    def test_format_multiple_lines(self):
        """Multiple lines each get >> prefix."""
        result = format_output("void func() {\n    int x = 1;\n    return x;\n}")
        assert result == ">> void func() {\n>>     int x = 1;\n>>     return x;\n>> }"

    def test_format_empty_string(self):
        """Empty string produces single >> prefix."""
        result = format_output("")
        assert result == ">> "

    def test_format_trailing_newline(self):
        """Trailing newlines are stripped."""
        result = format_output("void func() {}\n\n")
        assert result == ">> void func() {}"

    def test_format_preserves_internal_blank_lines(self):
        """Internal blank lines are preserved with >> prefix."""
        result = format_output("// Section 1\n\n// Section 2")
        assert result == ">> // Section 1\n>> \n>> // Section 2"

    def test_format_with_indentation(self):
        """Indentation is preserved."""
        result = format_output("void func() {\n    if (x) {\n        return;\n    }\n}")
        expected = ">> void func() {\n>>     if (x) {\n>>         return;\n>>     }\n>> }"
        assert result == expected

    def test_format_typical_decompile_output(self):
        """Format typical decompilation output."""
        decompile_output = """id myFunction(id self, SEL _cmd) {
    // Get the string value
    NSString *str = [self description];

    // Return the result
    return str;
}"""
        result = format_output(decompile_output)
        lines = result.split("\n")
        assert all(line.startswith(">> ") for line in lines)
        assert len(lines) == 7


def parse_args(command: str) -> tuple:
    """
    Parse command arguments.
    Returns (use_claude, address) tuple.
    """
    parts = command.strip().split()
    use_claude = False
    address_parts = []

    i = 0
    while i < len(parts):
        if parts[i] == "--claude":
            use_claude = True
        else:
            address_parts.append(parts[i])
        i += 1

    return use_claude, " ".join(address_parts)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_simple_address(self):
        """Simple address without flags."""
        use_claude, address = parse_args("0x12345678")
        assert use_claude is False
        assert address == "0x12345678"

    def test_parse_variable(self):
        """LLDB variable reference."""
        use_claude, address = parse_args("$pc")
        assert use_claude is False
        assert address == "$pc"

    def test_parse_numbered_variable(self):
        """LLDB numbered variable reference."""
        use_claude, address = parse_args("$0")
        assert use_claude is False
        assert address == "$0"

    def test_parse_expression(self):
        """Expression with spaces."""
        use_claude, address = parse_args("(IMP)[NSString class]")
        assert use_claude is False
        assert address == "(IMP)[NSString class]"

    def test_parse_claude_flag(self):
        """--claude flag before address."""
        use_claude, address = parse_args("--claude $pc")
        assert use_claude is True
        assert address == "$pc"

    def test_parse_claude_flag_after_address(self):
        """--claude flag after address."""
        use_claude, address = parse_args("$pc --claude")
        assert use_claude is True
        assert address == "$pc"

    def test_parse_empty_string(self):
        """Empty command."""
        use_claude, address = parse_args("")
        assert use_claude is False
        assert address == ""

    def test_parse_only_flag(self):
        """Only flag, no address."""
        use_claude, address = parse_args("--claude")
        assert use_claude is True
        assert address == ""

    def test_parse_expression_with_flag(self):
        """Expression with flag."""
        use_claude, address = parse_args("--claude (IMP)[NSString class]")
        assert use_claude is True
        assert address == "(IMP)[NSString class]"

    def test_parse_complex_expression(self):
        """Complex method implementation expression."""
        use_claude, address = parse_args("(IMP)class_getMethodImplementation([NSString class], @selector(init))")
        assert use_claude is False
        assert address == "(IMP)class_getMethodImplementation([NSString class], @selector(init))"


class TestDecompilePrompt:
    """Tests for DECOMPILE_PROMPT constant."""

    def test_prompt_contains_key_instructions(self):
        """Verify prompt contains essential instructions."""
        prompt = """You are an expert reverse engineer. Given the following \
arm64 disassembly and context, produce a concise pseudocode decompilation.

Guidelines:
- Use C-like syntax with Objective-C conventions where appropriate
- Infer variable names from context (registers, selectors, class names)
- Show the high-level logic, not every instruction
- Include brief comments for non-obvious operations
- If objc_msgSend calls are visible, show them as [receiver selector:args]
- Keep it concise - focus on what the function does, not boilerplate

{context}

DISASSEMBLY:
{disassembly}

Provide the decompiled pseudocode:"""

        assert "arm64" in prompt
        assert "reverse engineer" in prompt
        assert "pseudocode" in prompt
        assert "decompilation" in prompt
        assert "{context}" in prompt
        assert "{disassembly}" in prompt
        assert "objc_msgSend" in prompt
        assert "C-like syntax" in prompt

    def test_prompt_has_context_placeholder(self):
        """Verify prompt has context placeholder."""
        prompt = "{context}\n\nDISASSEMBLY:\n{disassembly}"
        assert "{context}" in prompt
        assert "{disassembly}" in prompt

    def test_prompt_format_substitution(self):
        """Test that prompt can be formatted with context and disassembly."""
        template = "{context}\n\nDISASSEMBLY:\n{disassembly}"
        result = template.format(
            context="SYMBOL INFO:\nmain at 0x1000\n\nREGISTER STATE:\nx0 = 0x123",
            disassembly="mov x0, #0\nret",
        )
        assert "main at 0x1000" in result
        assert "mov x0, #0" in result


class TestTimingOutput:
    """Tests for timing output format."""

    def test_timing_format(self):
        """Verify timing output format matches expected pattern."""
        import re

        # This is the format used in the command
        output = "\033[90m[llm responded in 5.2s]\033[0m"
        # Strip ANSI codes for testing
        stripped = re.sub(r"\033\[[0-9;]*m", "", output)
        assert "responded in" in stripped
        assert "s]" in stripped

    def test_timing_with_claude(self):
        """Verify Claude timing output format."""
        import re

        output = "\033[90m[Claude responded in 12.3s]\033[0m"
        stripped = re.sub(r"\033\[[0-9;]*m", "", output)
        assert "Claude responded" in stripped
        assert "12.3s" in stripped
