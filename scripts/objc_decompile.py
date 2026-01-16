#!/usr/bin/env python3
"""
LLDB script for decompiling disassembly using an LLM.

Usage: odecompile <address|$var|expression>   # Decompile function at address
       odecompile --claude <address>          # Use Claude CLI (opus model)
       odecompile --claude-haiku <address>    # Use Claude CLI (haiku model)
       odecompile 0x123456789abc              # Decompile by hex address
       odecompile $0                          # Decompile LLDB variable
       odecompile $pc                         # Decompile current function

This command disassembles the function at the given address and sends it
to an LLM for decompilation (llm by default, claude with --claude/--claude-haiku flags).
"""

from __future__ import annotations

import lldb
import os
import sys
import time
from typing import Any, Dict, Tuple

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Guard against double initialization
_initialized = False

from objc_llm import (
    get_disassembly,
    build_context,
    call_llm,
    call_claude,
    format_output,
)


DECOMPILE_PROMPT = """You are an expert reverse engineer specializing in Apple \
platforms. Given the following arm64 disassembly and context, produce a concise \
pseudocode decompilation.

Platform notes:
- ARM64 calling convention: x0-x7 are arguments, x0 is return value
- For Objective-C: x0=self, x1=_cmd (selector), x2+ are method arguments
- objc_msgSend(receiver, selector, args...) dispatches method calls
- Use the RESOLVED STRINGS and RESOLVED SELECTORS sections to understand what \
string constants and method selectors are being used

Guidelines:
- Use C-like syntax with Objective-C conventions where appropriate
- Infer variable names from context (registers, selectors, class names)
- Show the high-level logic, not every instruction
- Include brief comments for non-obvious operations
- If objc_msgSend calls are visible, show them as [receiver selector:args]
- Use resolved selector names to identify which methods are being called
- Keep it concise - focus on what the function does, not boilerplate
- Don't summarise at the end or provide any other context beyond the source code

{context}

DISASSEMBLY:
{disassembly}

Provide the decompiled pseudocode:"""


def parse_args(command: str) -> Tuple[str | None, str]:
    """
    Parse command arguments.

    Args:
        command: Raw command string

    Returns:
        (claude_model, address) tuple
        claude_model is None for llm, "opus" for --claude, "haiku" for --claude-haiku
    """
    parts = command.strip().split()
    claude_model = None
    address_parts = []

    i = 0
    while i < len(parts):
        if parts[i] == "--claude":
            claude_model = "opus"
        elif parts[i] == "--claude-haiku":
            claude_model = "haiku"
        else:
            address_parts.append(parts[i])
        i += 1

    return claude_model, " ".join(address_parts)


def decompile_command(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    LLDB command to decompile disassembly using an LLM.

    Usage: odecompile [--claude|--claude-haiku] <address|$var|expression>
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    claude_model, address = parse_args(command)

    if not address:
        result.SetError("Usage: odecompile [--claude|--claude-haiku] <address|$var|expression>")
        return

    # Get disassembly
    success, disasm = get_disassembly(debugger, address)
    if not success:
        result.SetError(f"Failed to disassemble: {disasm}")
        return

    if not disasm.strip():
        result.SetError("No disassembly output")
        return

    # Build context (symbol info + register state + resolved strings/selectors)
    context = build_context(debugger, address, disasm)

    # Build the prompt
    prompt = DECOMPILE_PROMPT.format(
        context=context if context else "(no additional context available)",
        disassembly=disasm.strip(),
    )

    if claude_model:
        backend = f"Claude ({claude_model})"
    else:
        backend = "llm"

    # Call LLM
    print(f"Sending {len(disasm.splitlines())} lines of disassembly to {backend} for decompilation...")
    start_time = time.time()

    if claude_model:
        success, decompilation = call_claude(prompt, claude_model)
    else:
        success, decompilation = call_llm(prompt)

    elapsed = time.time() - start_time

    if not success:
        result.SetError(decompilation)
        return

    # Print formatted output
    print(format_output(decompilation))
    print(f"\n\033[90m[{backend} responded in {elapsed:.1f}s]\033[0m")
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the odecompile command when this module is loaded in LLDB."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.decompile_command"
    debugger.HandleCommand(f"command script add -f {module_path} odecompile")
    print(f"[lldb-objc v{__version__}] 'odecompile' installed - Decompile with LLM")
