#!/usr/bin/env python3
"""
Bootstrap script to test the osbx (sandbox scanner) command.
Launches LLDB with HelloWorld and runs osbx to scan filesystem access.
"""

from bootstrap_common import (
    HELLOWORLD_PATH,
    verify_paths,
    run_lldb_session,
    make_commands_with_stop_at_entry,
)

verify_paths(HELLOWORLD_PATH)
print(f"Launching LLDB with {HELLOWORLD_PATH}")
print("Testing osbx command...")

# Build commands that stop at entry and then run osbx tests
commands = make_commands_with_stop_at_entry(HELLOWORLD_PATH)
commands += """
# Test osbx --help (should show help text, not run scan)
osbx --help

# Test quick scan (fastest, ~10 paths)
osbx --quick

# Test default scan with JSON output
osbx --json

# Test with a specific path prefix
osbx /tmp

# Test verbose mode on a small set
osbx --quick --verbose

# Test thorough mode (limited to a small prefix to keep test fast)
osbx --thorough --max-paths 50 /tmp

# Test filter option with ** recursive pattern
osbx --filter "/var/**"

# Test output to file
osbx --quick --output /tmp/osbx_test_output.txt
expr (void)system("cat /tmp/osbx_test_output.txt && rm /tmp/osbx_test_output.txt")
"""

run_lldb_session(HELLOWORLD_PATH, commands)
