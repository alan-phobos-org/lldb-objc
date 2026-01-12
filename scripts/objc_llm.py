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
import subprocess
from typing import Tuple


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
                ci = debugger.GetCommandInterpreter()
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
                ci = debugger.GetCommandInterpreter()
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


def call_claude(prompt: str) -> Tuple[bool, str]:
    """
    Send prompt to Claude via CLI.

    Args:
        prompt: The full prompt to send

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
                "opus",
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


def build_context(debugger: lldb.SBDebugger, address: str) -> str:
    """
    Build context string with symbol info and register state.

    Args:
        debugger: LLDB debugger instance
        address: Address being analyzed

    Returns:
        Context string to include in LLM prompt
    """
    context_parts = []

    # Get symbol info
    success, symbol_info = get_symbol_info(debugger, address)
    if success:
        context_parts.append(f"SYMBOL INFO:\n{symbol_info}")

    # Get register state
    success, reg_state = get_register_state(debugger)
    if success:
        context_parts.append(f"REGISTER STATE:\n{reg_state}")

    if context_parts:
        return "\n\n".join(context_parts)
    return ""
