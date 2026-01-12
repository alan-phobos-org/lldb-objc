#!/usr/bin/env python3
"""
Bootstrap script to launch LLDB with the HelloWorld-Optimised binary.
Tests command robustness against stripped/optimized binaries.

The optimised binary has:
- No debug symbols (stripped)
- Aggressive optimizations (-O3, -flto)
- Dead code elimination
- Hidden visibility

Stops at entry so the process stays paused for expression evaluation since
main/NSLog symbols may be stripped. Objective-C runtime metadata should still be
available.
"""

from bootstrap_common import (
    HELLOWORLD_OPTIMISED_PATH,
    verify_paths,
    run_lldb_session,
    make_commands_with_stop_at_entry,
)

verify_paths(HELLOWORLD_OPTIMISED_PATH, build_hint="cd examples/HelloWorld-Optimised && make")
print(f"Launching LLDB with OPTIMISED binary: {HELLOWORLD_OPTIMISED_PATH}")
print("This binary is stripped and heavily optimized - testing command robustness.\n")

run_lldb_session(
    HELLOWORLD_OPTIMISED_PATH,
    make_commands_with_stop_at_entry(HELLOWORLD_OPTIMISED_PATH),
)
