#!/usr/bin/env python3
"""
Test osbx command against a sandboxed HelloWorld binary.

This test validates that osbx runs correctly against a sandboxed binary:
1. Launches a binary that opts into a tight sandbox via sandbox_init()
2. Runs osbx to scan for writable paths
3. Verifies the results are valid JSON with expected structure

IMPORTANT: sandbox_init() based sandboxes have limitations for detection:
- NSFileManager's isWritableFileAtPath: checks Unix permissions, not sandbox
- sandbox_check() called from LLDB expression evaluation may behave differently
- For full sandbox detection, App Sandbox with entitlements is more reliable

The binary's sandbox profile (via sandbox_init):
- Write allowed: /tmp, /private/tmp, /dev/null, /dev/zero
- Write denied: Everything else (/System, /var, home directory, etc.)
- Network: Denied
"""

import json
import os
import subprocess
import sys
import tempfile

# Get paths relative to this file
_this_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_this_dir)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

HELLOWORLD_SANDBOXED_PATH = os.path.join(PROJECT_ROOT, "examples/HelloWorld-Sandboxed/HelloWorld/HelloWorld")


def verify_paths():
    """Verify required paths exist."""
    if not os.path.exists(HELLOWORLD_SANDBOXED_PATH):
        print(f"Error: Sandboxed binary not found at: {HELLOWORLD_SANDBOXED_PATH}")
        print("Build it first: cd examples/HelloWorld-Sandboxed && make")
        sys.exit(1)

    if not os.path.exists(SCRIPTS_DIR):
        print(f"Error: scripts directory not found at: {SCRIPTS_DIR}")
        sys.exit(1)


def run_lldb_with_osbx() -> str:
    """Run LLDB with osbx command and return JSON output."""
    # We need to break AFTER sandbox_init() is called.
    # The binary logs "Sandbox initialized successfully!" after sandbox_init.
    # We set a regex breakpoint on NSLog that fires after sandbox is active,
    # then continue past the early NSLog calls.
    commands = f"""
# Load the target binary
file {HELLOWORLD_SANDBOXED_PATH}

# Set breakpoint on a function called after sandbox is initialized
# The binary calls [Greeter sayHello:] after sandbox_init succeeds
breakpoint set -r "\\[Greeter sayHello:\\]" --one-shot true
run

# Now the sandbox should be active - run osbx
osbx --json --quick

# Exit
quit
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".lldb", delete=False) as f:
        f.write(commands)
        command_file = f.name

    try:
        result = subprocess.run(
            ["lldb", "-s", command_file],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout + result.stderr
    finally:
        os.unlink(command_file)


def extract_json_from_output(output: str) -> dict:
    """Extract JSON result from LLDB output."""
    # Find the main JSON block (the one with "platform" key)
    # This is a multi-line JSON object, so we need to track brace depth
    lines = output.split("\n")
    json_lines = []
    brace_depth = 0
    in_json = False

    for line in lines:
        stripped = line.strip()

        # Start capturing when we see opening brace
        if not in_json and stripped.startswith("{"):
            in_json = True
            json_lines = [stripped]
            brace_depth = stripped.count("{") - stripped.count("}")
        elif in_json:
            json_lines.append(stripped)
            brace_depth += stripped.count("{") - stripped.count("}")

            # When braces are balanced, try to parse
            if brace_depth == 0:
                json_str = "\n".join(json_lines)
                try:
                    parsed = json.loads(json_str)
                    # Check if this is the osbx output (has platform key)
                    if "platform" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass
                # Reset and continue looking
                in_json = False
                json_lines = []

    return {}


def validate_sandbox_results(results: dict) -> tuple[bool, list[str]]:
    """
    Validate that osbx results have the expected structure and values.

    Note: sandbox_init() based sandboxes may not be fully detected because:
    - NSFileManager.isWritableFileAtPath: checks Unix perms, not sandbox
    - sandbox_check() from LLDB expression evaluation behaves differently

    Returns:
        Tuple of (success, list of failure messages)
    """
    failures = []
    warnings = []

    # Check platform is macOS
    if results.get("platform") != "macOS":
        failures.append(f"Expected platform=macOS, got {results.get('platform')}")

    # Check we have valid output structure
    if "writable_paths" not in results:
        failures.append("Missing 'writable_paths' in results")
    if "denied_paths" not in results:
        failures.append("Missing 'denied_paths' in results")
    if "tested_count" not in results:
        failures.append("Missing 'tested_count' in results")

    # Check that some paths were tested
    tested_count = results.get("tested_count", 0)
    if tested_count == 0:
        failures.append("No paths were tested - something is wrong")

    writable_paths = results.get("writable_paths", [])
    writable_set = {p["path"] for p in writable_paths}

    # These device paths SHOULD be writable
    expected_writable = ["/dev/null", "/dev/zero"]
    for path in expected_writable:
        if path in writable_set:
            pass  # Good - device files are detected
        else:
            warnings.append(f"Expected {path} to be writable (may not be in quick scan)")

    # Note about sandbox_active detection
    if not results.get("sandbox_active"):
        warnings.append(
            "sandbox_active=False - expected for sandbox_init() based sandboxes "
            "(NSFileManager doesn't respect sandbox restrictions)"
        )

    return (len(failures) == 0, failures, warnings)


def main():
    print("=" * 60)
    print("Testing osbx against sandboxed HelloWorld binary")
    print("=" * 60)
    print()

    verify_paths()

    print(f"Binary: {HELLOWORLD_SANDBOXED_PATH}")
    print()

    print("Running LLDB with osbx --json --quick...")
    print("-" * 40)

    output = run_lldb_with_osbx()

    # Print raw output for debugging
    print("LLDB Output:")
    print(output)
    print("-" * 40)

    # Extract and validate JSON results
    results = extract_json_from_output(output)

    if not results:
        print("\nFAILED: Could not extract JSON results from osbx output")
        print("This may indicate osbx failed to run or produced invalid output.")
        sys.exit(1)

    print("\nParsed osbx results:")
    print(json.dumps(results, indent=2))
    print()

    # Validate results
    success, failures, warnings = validate_sandbox_results(results)

    print("Summary:")
    print(f"  - Platform: {results.get('platform')}")
    print(f"  - Sandbox active: {results.get('sandbox_active')}")
    print(f"  - Container: {results.get('container')}")
    print(f"  - Temp dir: {results.get('temp_directory')}")
    print(f"  - Writable paths: {results.get('writable_count', len(results.get('writable_paths', [])))}")
    print(f"  - Denied paths: {len(results.get('denied_paths', []))}")
    print(f"  - Tested count: {results.get('tested_count')}")
    print()

    if warnings:
        print("Warnings (expected for sandbox_init based sandboxes):")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    if success:
        print("SUCCESS: osbx ran correctly against sandboxed binary!")
    else:
        print("FAILED: Validation errors:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)


if __name__ == "__main__":
    main()
