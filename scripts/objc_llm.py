#!/usr/bin/env python3
"""
Shared utilities for LLM-based LLDB commands (oexplain, odecompile).

This module provides common functionality:
- Disassembly retrieval
- Symbol/function info lookup
- Register state capture
- LLM CLI wrappers (llm, claude)
- Output formatting
"""

from __future__ import annotations

import lldb
import re
import subprocess
from typing import List, Tuple


def get_disassembly(debugger: lldb.SBDebugger, address: str) -> Tuple[bool, str]:
    """
    Get disassembly at the given address using LLDB's disass command.

    Args:
        debugger: LLDB debugger instance
        address: Address expression to disassemble

    Returns:
        (success, output) tuple
    """
    result = lldb.SBCommandReturnObject()
    ci = debugger.GetCommandInterpreter()

    ci.HandleCommand(f"disass -a {address}", result)

    if result.Succeeded():
        return True, result.GetOutput()
    else:
        return False, result.GetError()


def get_symbol_info(debugger: lldb.SBDebugger, address: str) -> Tuple[bool, str]:
    """
    Get symbol information at the given address using image lookup.

    Args:
        debugger: LLDB debugger instance
        address: Address expression to look up

    Returns:
        (success, output) tuple with symbol name, module, and any available info
    """
    result = lldb.SBCommandReturnObject()
    ci = debugger.GetCommandInterpreter()

    ci.HandleCommand(f"image lookup -a {address}", result)

    if result.Succeeded():
        output = result.GetOutput().strip()
        if output:
            return True, output
        return False, "No symbol information found"
    else:
        return False, result.GetError()


def get_register_state(debugger: lldb.SBDebugger) -> Tuple[bool, str]:
    """
    Get current register state (x0-x7 for arm64 calling convention).

    For Objective-C: x0=self, x1=_cmd (selector), x2-x7=arguments.

    Args:
        debugger: LLDB debugger instance

    Returns:
        (success, output) tuple with register values and inferred types
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    if not frame.IsValid():
        return False, "No valid frame"

    lines = []
    regs = frame.GetRegisters()

    # Find general purpose registers
    gpr = None
    for reg_set in regs:
        if "general" in reg_set.GetName().lower():
            gpr = reg_set
            break

    if not gpr:
        return False, "Could not find general purpose registers"

    ci = debugger.GetCommandInterpreter()

    # Get x0-x7 (arm64 calling convention)
    for i in range(8):
        reg_name = f"x{i}"
        reg = gpr.GetChildMemberWithName(reg_name)
        if reg and reg.IsValid():
            value = reg.GetValueAsUnsigned()
            line = f"  {reg_name} = 0x{value:016x}"

            # Try to infer type info for x0 (self) and x1 (_cmd)
            if i == 0 and value != 0:
                # x0 is often 'self' - try to get class name
                class_result = lldb.SBCommandReturnObject()
                ci.HandleCommand(
                    f"expr -l objc -- (const char *)object_getClassName((id){value})",
                    class_result,
                )
                if class_result.Succeeded():
                    class_output = class_result.GetOutput().strip()
                    # Extract class name from output like '(const char *) $0 = "NSString"'
                    if '"' in class_output:
                        class_name = class_output.split('"')[1]
                        line += f"  (self: {class_name})"
            elif i == 1 and value != 0:
                # x1 is often _cmd (selector) - try to get selector name
                sel_result = lldb.SBCommandReturnObject()
                ci.HandleCommand(
                    f"expr -l objc -- (const char *)sel_getName((SEL){value})",
                    sel_result,
                )
                if sel_result.Succeeded():
                    sel_output = sel_result.GetOutput().strip()
                    if '"' in sel_output:
                        sel_name = sel_output.split('"')[1]
                        line += f"  (_cmd: {sel_name})"

            lines.append(line)

    if lines:
        return True, "Registers (arm64 calling convention):\n" + "\n".join(lines)
    return False, "Could not read registers"


def get_platform_info(debugger: lldb.SBDebugger) -> Tuple[bool, str]:
    """
    Get platform and architecture information.

    Args:
        debugger: LLDB debugger instance

    Returns:
        (success, output) tuple with platform details
    """
    target = debugger.GetSelectedTarget()
    if not target.IsValid():
        return False, "No valid target"

    triple = target.GetTriple()  # e.g., "arm64-apple-ios17.0.0"
    parts = triple.split("-") if triple else []

    arch = parts[0] if parts else "unknown"
    vendor = parts[1] if len(parts) > 1 else "unknown"
    os_info = parts[2] if len(parts) > 2 else "unknown"

    # Check for pointer authentication (arm64e)
    arch_desc = arch
    if arch == "arm64e":
        arch_desc = "arm64e (pointer authentication enabled)"

    lines = [
        f"Architecture: {arch_desc}",
        f"Platform: {vendor}-{os_info}",
        "Memory: stack grows down, frame pointer in x29, link register in x30",
    ]

    return True, "\n".join(lines)


def extract_addresses_from_disassembly(disassembly: str) -> List[int]:
    """
    Extract potential addresses from disassembly output.

    Looks for hex addresses in adrp, add, ldr patterns.

    Args:
        disassembly: Raw disassembly text

    Returns:
        List of unique addresses found
    """
    addresses = set()

    # Match addresses in comments like "; 0x1234567890"
    comment_pattern = r";\s*(0x[0-9a-fA-F]+)"
    for match in re.finditer(comment_pattern, disassembly):
        try:
            addr = int(match.group(1), 16)
            if addr > 0x1000:  # Skip small values
                addresses.add(addr)
        except ValueError:
            pass

    # Match addresses in bracket notation like "[0x1234567890]"
    bracket_pattern = r"\[(0x[0-9a-fA-F]+)\]"
    for match in re.finditer(bracket_pattern, disassembly):
        try:
            addr = int(match.group(1), 16)
            if addr > 0x1000:
                addresses.add(addr)
        except ValueError:
            pass

    return list(addresses)


def resolve_string_literals(debugger: lldb.SBDebugger, disassembly: str) -> Tuple[bool, str]:
    """
    Extract and resolve string literals from addresses in disassembly.

    Args:
        debugger: LLDB debugger instance
        disassembly: Raw disassembly text

    Returns:
        (success, output) tuple with resolved strings
    """
    addresses = extract_addresses_from_disassembly(disassembly)
    if not addresses:
        return False, "No addresses found"

    ci = debugger.GetCommandInterpreter()
    strings = []

    for addr in addresses[:20]:  # Limit to avoid too many lookups
        result = lldb.SBCommandReturnObject()

        # Try to read as C string
        ci.HandleCommand(f"memory read -f s -c 1 {addr}", result)

        if result.Succeeded():
            output = result.GetOutput().strip()
            # Parse output like: 0x1234: "hello world"
            if '"' in output:
                try:
                    string_val = output.split('"', 1)[1].rsplit('"', 1)[0]
                    # Only include if it looks like a real string
                    if len(string_val) >= 2 and string_val.isprintable():
                        strings.append(f'  0x{addr:x}: "{string_val}"')
                except (IndexError, ValueError):
                    pass

    if strings:
        return True, "String literals:\n" + "\n".join(strings[:10])  # Limit output
    return False, "No strings resolved"


def resolve_selectors(debugger: lldb.SBDebugger, disassembly: str) -> Tuple[bool, str]:
    """
    Resolve selectors referenced in the disassembly.

    Looks for selector references and resolves them via sel_getName.

    Args:
        debugger: LLDB debugger instance
        disassembly: Raw disassembly text

    Returns:
        (success, output) tuple with resolved selectors
    """
    # Find addresses that might be selectors (referenced before objc_msgSend)
    addresses = extract_addresses_from_disassembly(disassembly)
    if not addresses:
        return False, "No addresses found"

    ci = debugger.GetCommandInterpreter()
    selectors = []

    for addr in addresses[:20]:
        result = lldb.SBCommandReturnObject()

        # Try to interpret as selector
        ci.HandleCommand(
            f"expr -l objc -- (char *)sel_getName((SEL){addr})",
            result,
        )

        if result.Succeeded():
            output = result.GetOutput().strip()
            if '"' in output:
                try:
                    sel_name = output.split('"')[1]
                    # Valid selectors don't have spaces and aren't empty
                    if sel_name and " " not in sel_name and len(sel_name) < 100:
                        selectors.append(f"  0x{addr:x}: @selector({sel_name})")
                except (IndexError, ValueError):
                    pass

    if selectors:
        return True, "Selectors:\n" + "\n".join(selectors[:10])
    return False, "No selectors resolved"


def call_llm(prompt: str) -> Tuple[bool, str]:
    """
    Send prompt to llm CLI.

    Args:
        prompt: The full prompt to send

    Returns:
        (success, output) tuple
    """
    try:
        result = subprocess.run(
            ["llm", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return True, result.stdout
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            return False, f"llm CLI error: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "Error: llm CLI timed out after 120 seconds"
    except FileNotFoundError:
        return False, "Error: 'llm' CLI not found. Install with: pip install llm"
    except Exception as e:
        return False, f"Error calling llm: {e}"


def call_claude(prompt: str, model: str = "opus") -> Tuple[bool, str]:
    """
    Send prompt to Claude via CLI.

    Args:
        prompt: The full prompt to send
        model: Model to use (opus, haiku, etc.)

    Returns:
        (success, output) tuple
    """
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return True, result.stdout
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            return False, f"Claude CLI error: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "Error: Claude CLI timed out after 120 seconds"
    except FileNotFoundError:
        return (
            False,
            "Error: 'claude' CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
        )
    except Exception as e:
        return False, f"Error calling Claude: {e}"


def format_output(text: str) -> str:
    """Format LLM output with >> prefix on each line."""
    lines = text.rstrip().split("\n")
    return "\n".join(f">> {line}" for line in lines)


def build_context(debugger: lldb.SBDebugger, address: str, disassembly: str = "") -> str:
    """
    Build context string with symbol info, register state, and resolved references.

    Args:
        debugger: LLDB debugger instance
        address: Address being analyzed
        disassembly: Raw disassembly text (for resolving strings/selectors)

    Returns:
        Context string to include in LLM prompt
    """
    context_parts = []

    # Get platform/architecture info
    success, platform_info = get_platform_info(debugger)
    if success:
        context_parts.append(f"PLATFORM:\n{platform_info}")

    # Get symbol info
    success, symbol_info = get_symbol_info(debugger, address)
    if success:
        context_parts.append(f"SYMBOL INFO:\n{symbol_info}")

    # Get register state
    success, reg_state = get_register_state(debugger)
    if success:
        context_parts.append(f"REGISTER STATE:\n{reg_state}")

    # Resolve strings and selectors from disassembly
    if disassembly:
        success, strings = resolve_string_literals(debugger, disassembly)
        if success:
            context_parts.append(f"RESOLVED STRINGS:\n{strings}")

        success, selectors = resolve_selectors(debugger, disassembly)
        if success:
            context_parts.append(f"RESOLVED SELECTORS:\n{selectors}")

    if context_parts:
        return "\n\n".join(context_parts)
    return ""
