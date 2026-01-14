#!/usr/bin/env python3
"""
Bootstrap script to launch LLDB with the HelloWorld-Sandboxed binary.
Tests the osbx sandbox scanner command against a sandboxed process.

The sandboxed binary uses sandbox_init() with restrictions:
- File Write: Only /tmp, /private/tmp, /dev/null, /dev/zero
- File Read: Allowed (needed for runtime)
- Network: Denied
- Process: Fork/exec allowed

Stops at entry so the process stays paused for sandbox inspection.
"""

from bootstrap_common import (
    HELLOWORLD_SANDBOXED_PATH,
    verify_paths,
    run_lldb_session,
    make_commands_for_sandboxed_binary,
)

verify_paths(HELLOWORLD_SANDBOXED_PATH, build_hint="cd examples/HelloWorld-Sandboxed && make")
print(f"Launching LLDB with SANDBOXED binary: {HELLOWORLD_SANDBOXED_PATH}")
print("This binary has active sandbox restrictions - testing osbx command.\n")

run_lldb_session(
    HELLOWORLD_SANDBOXED_PATH,
    make_commands_for_sandboxed_binary(HELLOWORLD_SANDBOXED_PATH),
)
