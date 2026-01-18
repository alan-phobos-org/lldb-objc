#!/usr/bin/env python3
"""
Bootstrap script to attach LLDB to the running apsd system process.
Tests commands against a real system daemon without loading additional libraries.

apsd (Apple Push Service Daemon) is a system daemon that manages push notifications.
This test ensures the LLDB Objective-C commands work on production system processes
in their native state without any framework loading.

Note: Requires sudo/root permissions to attach to system processes.
"""

from bootstrap_common import (
    run_lldb_session,
    make_commands_for_system_process,
)

PROCESS_NAME = "apsd"

print(f"Attaching LLDB to system process: {PROCESS_NAME}")
print("This tests commands against a real system daemon without library loading.")
print("Note: You may need sudo privileges to attach to system processes.\n")

run_lldb_session(None, make_commands_for_system_process(PROCESS_NAME), use_sudo=True)
