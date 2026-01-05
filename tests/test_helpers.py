#!/usr/bin/env python3
"""
Shared test infrastructure for LLDB Objective-C automation tests.

Provides common utilities for:
- Running LLDB with command scripts
- Parsing output and timing metrics
- Test result tracking with pytest-style output
- Test timeout management (60-second max per test)
- Shared LLDB session support for faster test execution
- Python traceback detection for command script errors
- Consolidated validator utilities to reduce duplication
"""

import subprocess
import os
import re
import time
import signal
import functools

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
HELLO_WORLD_PATH = os.path.join(PROJECT_ROOT, 'examples/HelloWorld/HelloWorld/HelloWorld')

# Test timeout in seconds (1 minute max per test case)
TEST_TIMEOUT_SECONDS = 60


class TestTimeoutError(Exception):
    """Raised when a test exceeds the timeout limit."""
    pass


def timeout_handler(signum, frame):
    """Signal handler for test timeouts."""
    raise TestTimeoutError(f"Test exceeded {TEST_TIMEOUT_SECONDS}s timeout")


def with_timeout(timeout_seconds=TEST_TIMEOUT_SECONDS):
    """
    Decorator to add a timeout to a test function.

    Args:
        timeout_seconds: Maximum time allowed for the test (default: 60s)

    Returns:
        Decorated function that will fail if it exceeds the timeout.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Set up the signal handler
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)
            try:
                return func(*args, **kwargs)
            except TestTimeoutError:
                # Return a failed TestResult
                test = TestResult(func.__doc__ or func.__name__)
                test.fail(f"TIMEOUT: Test exceeded {timeout_seconds}s limit")
                return test
            finally:
                # Restore the old handler and cancel the alarm
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        return wrapper
    return decorator


def check_hello_world_binary():
    """Check if HelloWorld binary exists, exit with instructions if not."""
    if not os.path.exists(HELLO_WORLD_PATH):
        print(f"Error: HelloWorld binary not found at {HELLO_WORLD_PATH}")
        print("Please build the HelloWorld example first:")
        print("  cd examples/HelloWorld && xcodebuild")
        return False
    return True


def run_lldb_test(commands, scripts=None, timeout=30, load_ids_framework=True):
    """
    Run LLDB with a series of commands and return the output.

    Args:
        commands: List of LLDB commands to execute
        scripts: List of script paths to import (e.g., ['objc_cls.py', 'objc_sel.py'])
        timeout: Timeout in seconds
        load_ids_framework: Whether to load IDS.framework for private class testing

    Returns:
        Tuple of (stdout, stderr, return_code)
    """
    # Build command list using -o flags for reliable execution
    cmd_args = ['lldb', '-b']

    # Add script imports (only if not already loaded by lldbinit)
    if scripts:
        # First, allow overwrites to handle lldbinit already loading these
        cmd_args.extend(['-o', 'settings set interpreter.require-overwrite false'])
        for script in scripts:
            script_path = os.path.join(PROJECT_ROOT, script)
            cmd_args.extend(['-o', f'command script import {script_path}'])

    # Setup commands
    cmd_args.extend(['-o', f'file {HELLO_WORLD_PATH}'])
    cmd_args.extend(['-o', 'breakpoint set -n "HelloWorld`main"'])
    cmd_args.extend(['-o', 'run'])
    cmd_args.extend(['-o', 'breakpoint delete 1'])  # Clear the main breakpoint after hit

    if load_ids_framework:
        cmd_args.extend(['-o', 'expr (void)dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", 0x2)'])

    # Add user commands
    for cmd in commands:
        cmd_args.extend(['-o', cmd])

    cmd_args.extend(['-o', 'quit'])

    # Run LLDB
    try:
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1


class TestResult:
    """Track test results with optional performance metrics."""

    def __init__(self, name):
        self.name = name
        self.passed = False
        self.message = ""
        self.metrics = {}
        self.execution_time = 0
        self.failure_detail = None

    def pass_(self, msg="", metrics=None):
        self.passed = True
        self.message = msg
        if metrics:
            self.metrics = metrics

    def fail(self, msg, detail=None):
        self.passed = False
        self.message = msg
        self.failure_detail = detail


def parse_timing_metrics(output):
    """
    Parse timing metrics from command output.

    Looks for patterns like:
    - [N methods | X expressions | Y memory reads | Z.ZZs]
    - Instance methods (N)
    - Class methods (N)
    - Total: N methods

    Returns:
        dict with parsed metrics, or empty dict if not parseable
    """
    metrics = {}

    # Parse method counts
    instance_match = re.search(r'Instance methods \((\d+)\)', output)
    class_match = re.search(r'Class methods \((\d+)\)', output)
    total_match = re.search(r'Total: (\d+) method', output)

    if instance_match:
        metrics['instance_methods'] = int(instance_match.group(1))
    if class_match:
        metrics['class_methods'] = int(class_match.group(1))
    if total_match:
        metrics['total_methods'] = int(total_match.group(1))

    # Parse performance metrics
    expr_match = re.search(r'(\d+)\s*expressions?', output, re.IGNORECASE)
    mem_match = re.search(r'(\d+)\s*memory\s*reads?', output, re.IGNORECASE)
    time_match = re.search(r'(\d+\.?\d*)\s*s\]', output)

    if expr_match:
        metrics['expressions'] = int(expr_match.group(1))
    if mem_match:
        metrics['memory_reads'] = int(mem_match.group(1))
    if time_match:
        metrics['time_seconds'] = float(time_match.group(1))

    return metrics


def run_test_suite(name, tests, show_category_summary=None):
    """
    Run a list of test functions and print results.

    Each test is wrapped with a 60-second timeout. If a test exceeds this limit,
    it will be marked as failed with a TIMEOUT message.

    Args:
        name: Name of the test suite
        tests: List of test functions (each returns a TestResult)
        show_category_summary: Optional dict mapping category names to test index ranges

    Returns:
        (passed_count, total_count)
    """
    print("=" * 70)
    print(name)
    print("=" * 70)
    print(f"Binary: {HELLO_WORLD_PATH}")
    print(f"Timeout: {TEST_TIMEOUT_SECONDS}s per test")

    if not check_hello_world_binary():
        return 0, len(tests)

    results = []
    suite_start_time = time.time()

    for i, test_func in enumerate(tests, 1):
        test_name = test_func.__doc__ or test_func.__name__

        # Time the test execution with timeout
        test_start_time = time.time()

        # Set up signal-based timeout
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(TEST_TIMEOUT_SECONDS)

        try:
            result = test_func()
        except TestTimeoutError:
            result = TestResult(test_name)
            result.fail(f"TIMEOUT: Test exceeded {TEST_TIMEOUT_SECONDS}s limit")
        except Exception as e:
            result = TestResult(test_name)
            result.fail(f"EXCEPTION: {str(e)}")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        test_elapsed = time.time() - test_start_time
        result.execution_time = test_elapsed

        results.append(result)
        status = "✅" if result.passed else "❌"
        print(f"[{i:2}/{len(tests)}] {status} {test_elapsed:5.2f}s  {result.name}")

    suite_elapsed = time.time() - suite_start_time

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\nTotal: {passed}/{total} passed in {suite_elapsed:.1f}s")

    return passed, total


# =============================================================================
# Shared LLDB Session Support
# =============================================================================

class SharedLLDBSession:
    """
    A shared LLDB session that persists across multiple test commands.

    This dramatically improves test performance by avoiding the overhead
    of starting a new LLDB process for each test (typically 4-6s per spawn).

    Uses pexpect for reliable interaction with LLDB's interactive mode.

    Usage:
        with SharedLLDBSession(scripts=['objc_breakpoint.py']) as session:
            output = session.run_command('obrk -[NSString length]')
            output = session.run_command('breakpoint list')
            session.clear_breakpoints()  # Clean state for next test
    """

    def __init__(self, scripts=None, load_ids_framework=True, timeout=30):
        """
        Initialize the shared LLDB session.

        Args:
            scripts: List of script paths to import (e.g., ['objc_breakpoint.py'])
            load_ids_framework: Whether to load IDS.framework for private class testing
            timeout: Default timeout for commands in seconds
        """
        self.scripts = scripts or []
        self.load_ids_framework = load_ids_framework
        self.default_timeout = timeout
        self.child = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    @staticmethod
    def _strip_ansi(text):
        """Remove ANSI escape sequences from text."""
        import re
        # Pattern matches various ANSI escape sequences
        ansi_pattern = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x07|\r')
        return ansi_pattern.sub('', text)

    def start(self):
        """Start the LLDB session using pexpect."""
        import pexpect

        if self.child is not None:
            return

        # Environment with disabled LLDB progress reporting
        env = os.environ.copy()
        env['TERM'] = 'dumb'  # Disable terminal features

        # Start LLDB in non-interactive style
        self.child = pexpect.spawn(
            'lldb',
            encoding='utf-8',
            timeout=self.default_timeout,
            env=env
        )
        self.child.setwinsize(200, 500)  # Set large window to avoid line wrapping

        # Wait for initial prompt
        self.child.expect(r'\(lldb\)')

        # Disable terminal features that interfere with output parsing
        self.child.sendline('settings set use-color false')
        self.child.expect(r'\(lldb\)')
        self.child.sendline('settings set show-progress false')
        self.child.expect(r'\(lldb\)')
        self.child.sendline('settings set auto-confirm true')
        self.child.expect(r'\(lldb\)')

        # Send initialization commands
        init_commands = []

        # Allow overwrites for scripts that may already be loaded
        init_commands.append('settings set interpreter.require-overwrite false')

        # Import scripts
        for script in self.scripts:
            script_path = os.path.join(PROJECT_ROOT, script)
            init_commands.append(f'command script import {script_path}')

        # Set up target and run
        init_commands.append(f'file {HELLO_WORLD_PATH}')
        init_commands.append('breakpoint set -n main')
        init_commands.append('run')

        # Load IDS framework if requested
        if self.load_ids_framework:
            init_commands.append('expr (void)dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", 0x2)')

        # Execute each init command
        for cmd in init_commands:
            self.child.sendline(cmd)
            self.child.expect(r'\(lldb\)', timeout=60)

        # Clear the main breakpoint after it's been hit
        self.child.sendline('breakpoint delete 1')
        self.child.expect(r'\(lldb\)')

    def run_command(self, cmd, timeout=None):
        """
        Run a command in the LLDB session and return output.

        Args:
            cmd: The LLDB command to run
            timeout: Optional timeout override

        Returns:
            The command output as a string
        """
        import pexpect

        if not self.child:
            raise RuntimeError("LLDB session not started")

        timeout = timeout or self.default_timeout

        # Send the command
        self.child.sendline(cmd)

        # Wait for the prompt
        try:
            self.child.expect(r'\(lldb\)', timeout=timeout)
        except pexpect.TIMEOUT:
            return f"TIMEOUT waiting for command: {cmd}"

        # Get the output (everything between command echo and prompt)
        output = self.child.before

        # Strip ANSI escape sequences
        output = self._strip_ansi(output)

        # Check for Python tracebacks/errors that indicate command script failures
        if 'Traceback (most recent call last):' in output:
            # Preserve the full traceback for debugging
            return f"ERROR: Command script failed with exception:\n{output}"

        # Clean up the output
        lines = output.split('\n')
        filtered_lines = []
        for line in lines:
            # Skip the echoed command
            stripped = line.strip()
            if stripped == cmd:
                continue
            # Skip lines that are just the command with (lldb) prefix
            if stripped.endswith(cmd) and '(lldb)' in line:
                continue
            # Skip progress indicator lines (usually contain │ or similar)
            if '│' in line or 'Locating external symbol' in line or 'Parsing symbol' in line:
                continue
            if 'Loading DWARF' in line:
                continue
            # Skip empty lines at start
            if not filtered_lines and not stripped:
                continue
            filtered_lines.append(line)

        # Remove trailing empty lines
        while filtered_lines and not filtered_lines[-1].strip():
            filtered_lines.pop()

        return '\n'.join(filtered_lines)

    def run_commands(self, commands, timeout=None):
        """
        Run multiple commands and return combined output.

        Args:
            commands: List of LLDB commands to run
            timeout: Optional timeout override

        Returns:
            The combined command output as a string
        """
        output_parts = []
        for cmd in commands:
            result = self.run_command(cmd, timeout)
            if result.strip():  # Only add non-empty results
                output_parts.append(result)
        return '\n'.join(output_parts)

    def clear_breakpoints(self):
        """Clear all breakpoints to reset state between tests."""
        return self.run_command('breakpoint delete -f')

    def stop(self):
        """Stop the LLDB session."""
        if self.child:
            try:
                self.child.sendline('quit')
                import pexpect
                self.child.expect(pexpect.EOF, timeout=5)
            except Exception:
                pass
            finally:
                self.child.close()
                self.child = None


# =============================================================================
# Pytest-Style Test Runner
# =============================================================================

def run_shared_test_suite(name, test_specs, scripts=None, show_category_summary=None,
                          warmup_commands=None):
    """
    Run a list of tests using a shared LLDB session with pytest-style output.

    This is significantly faster than run_test_suite because it avoids
    spawning a new LLDB process for each test.

    Args:
        name: Name of the test suite
        test_specs: List of (test_name, commands, validator_func) tuples
            - test_name: Display name for the test
            - commands: List of LLDB commands to run
            - validator_func: Function(output) -> (passed, message)
        scripts: List of script paths to import
        show_category_summary: Optional dict mapping category names to test index ranges
        warmup_commands: Optional list of commands to run before tests (e.g., cache warming)

    Returns:
        (passed_count, total_count)
    """
    if not check_hello_world_binary():
        return 0, len(test_specs)

    results = []
    suite_start_time = time.time()

    # Print header in pytest style
    print(f"{'=' * 70}")
    print(f"test session starts")
    print(f"platform darwin -- Python {'.'.join(map(str, __import__('sys').version_info[:3]))}")
    print(f"collected {len(test_specs)} items\n")

    # Start shared session
    session_start = time.time()

    with SharedLLDBSession(scripts=scripts) as session:
        session_init_time = time.time() - session_start

        # Run warmup commands if provided (e.g., cache pre-warming)
        if warmup_commands:
            for cmd in warmup_commands:
                session.run_command(cmd, timeout=120)  # Allow longer timeout for warmup

        # Track failures for detailed output later
        failures = []

        for i, (test_name, commands, validator) in enumerate(test_specs, 1):
            test_start_time = time.time()
            result = TestResult(test_name)

            try:
                # Clear breakpoints before each test to ensure clean state
                session.clear_breakpoints()

                # Run commands and collect output
                output = session.run_commands(commands)

                # Check for command script errors
                if output.startswith("ERROR: Command script failed"):
                    result.fail("Command script error detected", detail=output)
                else:
                    # Validate results
                    passed, message = validator(output)
                    if passed:
                        result.pass_(message)
                    else:
                        result.fail(message, detail=output)

            except Exception as e:
                result.fail(f"EXCEPTION: {str(e)}", detail=str(e))

            test_elapsed = time.time() - test_start_time
            result.execution_time = test_elapsed
            results.append(result)

            # Pytest-style inline progress with dots/F
            if result.passed:
                print(".", end="", flush=True)
            else:
                print("F", end="", flush=True)
                failures.append((i, result, output))

            # Line break every 60 characters or at end
            if i % 60 == 0 or i == len(test_specs):
                percentage = int(100 * i / len(test_specs))
                print(f" [{percentage:3d}%]")

    suite_elapsed = time.time() - suite_start_time

    # Print failures section (pytest style)
    if failures:
        print(f"\n{'=' * 70}")
        print("FAILURES")
        print(f"{'=' * 70}")

        for test_idx, result, output in failures:
            print(f"\n{'_' * 70}")
            print(f"{result.name}")
            print(f"{'_' * 70}\n")

            # Show the failure message
            print(result.message)

            # Show truncated output if available
            if result.failure_detail:
                print(f"\n  Output (first 500 chars):")
                print(f"  {result.failure_detail[:500]}")
                if len(result.failure_detail) > 500:
                    print(f"  ... ({len(result.failure_detail) - 500} more characters)")

    # Print summary line (pytest style)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    failed = total - passed

    print(f"\n{'=' * 70}")

    if failed == 0:
        print(f"\033[92m{passed} passed\033[0m in {suite_elapsed:.2f}s")
    else:
        parts = []
        if failed > 0:
            parts.append(f"\033[91m{failed} failed\033[0m")
        if passed > 0:
            parts.append(f"\033[92m{passed} passed\033[0m")
        print(f"{', '.join(parts)} in {suite_elapsed:.2f}s")

    print(f"{'=' * 70}")

    return passed, total


# =============================================================================
# Consolidated Validator Utilities
# =============================================================================

class Validators:
    """Consolidated validator factory to reduce duplication across test files."""

    @staticmethod
    def contains(substring, error_prefix="Expected content not found"):
        """Validator that checks if output contains a substring."""
        def validator(output):
            if substring in output:
                return True, f"Contains '{substring}'"
            return False, f"{error_prefix}\n  Expected: '{substring}' in output\n  Actual: Not found"
        return validator

    @staticmethod
    def contains_any(*substrings, error_prefix="Expected content not found"):
        """Validator that checks if output contains any of the given substrings."""
        def validator(output):
            for s in substrings:
                if s in output:
                    return True, f"Contains '{s}'"
            return False, f"{error_prefix}\n  Expected any of: {substrings}\n  Actual: None found"
        return validator

    @staticmethod
    def contains_all(*substrings, error_prefix="Expected content not found"):
        """Validator that checks if output contains all of the given substrings."""
        def validator(output):
            missing = [s for s in substrings if s not in output]
            if not missing:
                return True, f"Contains all: {substrings}"
            return False, f"{error_prefix}\n  Expected all of: {substrings}\n  Missing: {missing}"
        return validator

    @staticmethod
    def regex_match(pattern, error_prefix="Pattern not matched"):
        """Validator that checks if output matches a regex pattern."""
        def validator(output):
            match = re.search(pattern, output)
            if match:
                return True, f"Matches pattern '{pattern}'"
            return False, f"{error_prefix}\n  Pattern: {pattern}\n  Actual: No match"
        return validator

    @staticmethod
    def count_minimum(pattern, min_count, error_prefix="Insufficient matches"):
        """Validator that checks if a pattern appears at least min_count times."""
        def validator(output):
            matches = re.findall(pattern, output)
            count = len(matches)
            if count >= min_count:
                return True, f"Found {count} matches (>= {min_count})"
            return False, f"{error_prefix}\n  Expected: >= {min_count}\n  Actual: {count}"
        return validator

    @staticmethod
    def breakpoint_created(error_prefix="Breakpoint not created"):
        """Validator for breakpoint creation (checks for 'Breakpoint #' and 'IMP:')."""
        def validator(output):
            if 'Breakpoint #' in output and 'IMP:' in output:
                return True, "Breakpoint created successfully"
            return False, f"{error_prefix}\n  Expected: 'Breakpoint #' and 'IMP:' in output\n  Actual: Not found"
        return validator

    @staticmethod
    def error_reported(error_prefix="Error not reported"):
        """Validator that checks if an error message is present."""
        def validator(output):
            if 'error' in output.lower() or 'not found' in output.lower() or 'usage' in output.lower():
                return True, "Error properly reported"
            return False, f"{error_prefix}\n  Expected: Error message in output\n  Actual: No error found"
        return validator

    @staticmethod
    def custom(check_func, pass_msg="Check passed", fail_msg="Check failed"):
        """Validator with custom check function."""
        def validator(output):
            if check_func(output):
                return True, pass_msg
            return False, fail_msg
        return validator

    @staticmethod
    def combine_and(*validators):
        """Combine multiple validators with AND logic."""
        def validator(output):
            for v in validators:
                passed, msg = v(output)
                if not passed:
                    return False, msg
            return True, "All checks passed"
        return validator

    @staticmethod
    def combine_or(*validators):
        """Combine multiple validators with OR logic."""
        def validator(output):
            messages = []
            for v in validators:
                passed, msg = v(output)
                if passed:
                    return True, msg
                messages.append(msg)
            return False, f"All checks failed:\n" + "\n".join(f"  - {m}" for m in messages)
        return validator
