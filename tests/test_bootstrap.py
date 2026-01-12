#!/usr/bin/env python3
"""
Bootstrap script to launch LLDB with the HelloWorld binary and set up testing environment.
Sets breakpoint on main, runs process, and loads IDS.framework.
"""

from bootstrap_common import (
    HELLOWORLD_PATH,
    verify_paths,
    run_lldb_session,
    make_commands_with_main_breakpoint,
)

verify_paths(HELLOWORLD_PATH)
print(f"Launching LLDB with {HELLOWORLD_PATH}")

run_lldb_session(HELLOWORLD_PATH, make_commands_with_main_breakpoint(HELLOWORLD_PATH))
