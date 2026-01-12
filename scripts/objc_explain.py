#!/usr/bin/env python3
"""
LLDB script for explaining disassembly using an LLM.

Usage: oexplain <address|$var|expression>   # Explain disassembly at address
       oexplain -a <address>                # Annotate each line of disassembly
       oexplain --claude <address>          # Use Claude CLI instead of llm
       oexplain 0x123456789abc              # Explain by hex address
       oexplain $0                          # Explain LLDB variable
       oexplain (IMP)[NSString class]       # Explain by expression

This command disassembles the function at the given address and sends it to
an LLM for analysis (llm by default, claude with --claude flag).
"""

from __future__ import annotations

import lldb
import os
import sys
import time
from typing import Any, Dict

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

from objc_llm import (
    get_disassembly,
    build_context,
    call_llm,
    call_claude,
    format_output,
)


EXPLAIN_PROMPT = """You are an expert reverse engineer. Given the following \
arm64 disassembly and context, explain very concisely what this function does \
as you would to a security researcher. Avoid boilerplate. Include a compact \
view of the first 5 functions it will call.

{context}

DISASSEMBLY:
{disassembly}

Explain concisely:"""

ANNOTATE_PROMPT = """You are an expert reverse engineer. Given the following \
arm64 disassembly and context, reproduce the disassembly exactly, but add \
concise high-level annotations as comments on lines where the purpose isn't \
obvious. Focus on what's happening semantically (e.g., "// get string length", \
"// check for nil", "// call objc_msgSend with selector"). Skip trivial \
operations like stack frame setup. Keep annotations brief.

{context}

DISASSEMBLY:
{disassembly}

Annotated disassembly:"""


def parse_args(command: str) -> tuple[bool, bool, str]:
    """
    Parse command arguments.

    Args:
        command: Raw command string

    Returns:
        (annotate_mode, use_claude, address) tuple
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


def explain_command(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    LLDB command to explain disassembly using an LLM.

    Usage: oexplain [-a|--annotate] [--claude] <address|$var|expression>
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    annotate, use_claude, address = parse_args(command)

    if not address:
        result.SetError("Usage: oexplain [-a|--annotate] [--claude] <address|$var|expression>")
        return

    # Get disassembly
    success, disasm = get_disassembly(debugger, address)
    if not success:
        result.SetError(f"Failed to disassemble: {disasm}")
        return

    if not disasm.strip():
        result.SetError("No disassembly output")
        return

    # Build context (symbol info + register state)
    context = build_context(debugger, address)

    # Select prompt based on mode
    prompt_template = ANNOTATE_PROMPT if annotate else EXPLAIN_PROMPT
    prompt = prompt_template.format(
        context=context if context else "(no additional context available)",
        disassembly=disasm.strip(),
    )

    mode_desc = "annotating" if annotate else "explaining"
    backend = "Claude" if use_claude else "llm"

    # Call LLM
    print(f"Sending {len(disasm.splitlines())} lines of disassembly to {backend} ({mode_desc})...")
    start_time = time.time()
    if use_claude:
        success, explanation = call_claude(prompt)
    else:
        success, explanation = call_llm(prompt)
    elapsed = time.time() - start_time

    if not success:
        result.SetError(explanation)
        return

    # Print formatted output
    print(format_output(explanation))
    print(f"\n\033[90m[{backend} responded in {elapsed:.1f}s]\033[0m")
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the oexplain command when this module is loaded in LLDB."""
    module_path = f"{__name__}.explain_command"
    debugger.HandleCommand(f"command script add -f {module_path} oexplain")
    print(f"[lldb-objc v{__version__}] 'oexplain' installed - Explain disassembly with LLM")
