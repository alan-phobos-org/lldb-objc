# Test Suite Documentation

## Overview

The lldb-objc project has a comprehensive test suite covering all implemented commands.
Tests are organized by feature and can be run individually or as a complete suite.

## Quick Start

```bash
# Run all implemented feature tests
./tests/run_all_tests.py

# Run quick subset of tests (faster)
./tests/run_all_tests.py --quick

# Run specific test suites
./tests/run_all_tests.py obrk ocls

# Include performance tests
./tests/run_all_tests.py --perf

# Include future/unimplemented feature tests
./tests/run_all_tests.py --all

# Show verbose output
./tests/run_all_tests.py --verbose
```

## Prerequisites

Before running tests, build the HelloWorld example binary:

```bash
cd examples/HelloWorld && xcodebuild
```

The tests use this binary as a target for LLDB debugging.

## Test Structure

```
tests/
├── run_all_tests.py      # Unified test runner (pytest-style output)
├── test_helpers.py       # Shared test infrastructure
├── test_obrk.py          # obrk command tests
├── test_ocls.py          # ocls command tests
├── test_osel.py          # osel command tests
├── test_ocall.py         # ocall command tests
├── test_owatch.py        # owatch command tests
├── test_oprotos.py       # oprotos command tests
├── test_hierarchy.py     # Class hierarchy display tests
├── test_ivars_props.py   # --ivars and --properties flag tests
├── test_osel_perf.py     # osel performance optimization tests
├── test_timing.py        # Performance timing tests
└── test_bootstrap.py     # Interactive LLDB setup script
```

## Test Suites

### Implemented Features

| Suite | File | Description | Tests |
|-------|------|-------------|-------|
| `obrk` | `test_obrk.py` | Breakpoint command | 14 |
| `ocls` | `test_ocls.py` | Class finder | 23 |
| `osel` | `test_osel.py` | Selector finder | 18 |
| `ocall` | `test_ocall.py` | Method caller | 9 |
| `owatch` | `test_owatch.py` | Method watcher | 8 |
| `oprotos` | `test_oprotos.py` | Protocol conformance | 8 |
| `hierarchy` | `test_hierarchy.py` | Hierarchy display | 7 |
| `ivars_props` | `test_ivars_props.py` | Ivars/properties | 13 |
| `osel_perf` | `test_osel_perf.py` | osel performance | 8 |

### Performance Tests

| Suite | File | Description |
|-------|------|-------------|
| `timing` | `test_timing.py` | Detailed timing measurements |

## Test Categories

Each test suite is organized into categories. For example, `test_obrk.py`:

- **Basic functionality**: Instance/class methods, private classes
- **Complex selectors**: Multi-argument methods
- **Error handling**: Invalid class/selector, syntax errors
- **Validation**: Address verification, naming
- **Edge cases**: Root class, metaclass

## Writing New Tests

### Test Structure

Tests use the shared infrastructure from `test_helpers.py`:

```python
from test_helpers import (
    run_lldb_test, TestResult, run_test_suite
)

def test_my_feature():
    """Test description shown during execution."""
    test = TestResult("My Feature Test")

    stdout, stderr, _ = run_lldb_test(
        ['my_command arg1 arg2'],
        scripts=['my_script.py'],
        timeout=30
    )
    output = stdout + stderr

    if 'expected output' in output:
        test.pass_("Feature works correctly")
    else:
        test.fail(f"Unexpected: {output[:200]}")

    return test

def main():
    tests = [test_my_feature]
    passed, total = run_test_suite("MY TEST SUITE", tests)
    sys.exit(0 if passed == total else 1)
```

### Test Helpers API

```python
# Run LLDB with commands
stdout, stderr, returncode = run_lldb_test(
    commands=['ocls NSString'],      # LLDB commands to run
    scripts=['objc_cls.py'],         # Scripts to load
    timeout=30,                       # Timeout in seconds
    load_ids_framework=True           # Load IDS.framework
)

# Track test results
result = TestResult("Test Name")
result.pass_("Success message")       # Mark as passed
result.fail("Failure reason")         # Mark as failed
result.metrics = {'key': 'value'}     # Optional metrics

# Run test suite with summary
passed, total = run_test_suite(
    "SUITE NAME",
    [test_func1, test_func2],
    show_category_summary={'Category': (0, 2)}  # Optional
)
```

## Manual Testing

For interactive testing, use `test_bootstrap.py`:

```bash
python3 tests/test_bootstrap.py
```

This launches LLDB with the HelloWorld binary, sets up breakpoints,
loads the IDS framework, and imports all objc commands.

### Manual Test Cases for osel

These manual tests supplement the automated test suite:

#### Test 1: List All Selectors
```
osel IDSService
```
**Expected:** Should list all instance and class methods in IDSService

#### Test 2: Find 'serviceIdentifier' Selector
```
osel IDSService serviceIdentifier
```
**Expected:** Should find and display the `serviceIdentifier` method

#### Test 3: Pattern Match
```
osel IDSService *service*
```
**Expected:** Should display all methods containing "service"

### Debugging Tips

If a command fails:
- Check that the process is stopped: `process status`
- Verify class exists: `expr (Class)NSClassFromString(@"IDSService")`
- Try a simpler class first: `osel NSString length`

## Output Format

The test runner uses pytest-style output for consistency:

### Normal Mode
```
======================================================================
test session starts
platform darwin -- Python 3.11.6
collected 9 test suites

......... [100%]

======================================================================
9 passed in 234.56s
(108 passed tests total)
======================================================================
```

### With Failures
```
======================================================================
test session starts
platform darwin -- Python 3.11.6
collected 2 test suites

.F [100%]

======================================================================
FAILURES
======================================================================

______________________________________________________________________
ocall :: Objective-C method caller
Result: 8/9 passed (5.50s)
______________________________________________________________________

  Instance method from variable

  Command failed
    Expected: 'TestString' in output
    Actual: Error encountered
    Output preview: error: Method call failed...
    ... (233 more characters)

  Re-run this suite: python3 tests/test_ocall.py

======================================================================
1 failed, 1 passed in 12.40s
(1 failed, 22 passed tests total)
======================================================================
```

The output provides:
- Suite-level progress (`.` for pass, `F` for fail)
- Detailed failure information with first 300 chars of output
- Instructions to re-run failing suites
- Both suite-level and test-level summary statistics

### Verbose Mode
```bash
./tests/run_all_tests.py --verbose
```
Shows full output from each individual test suite as it runs.

## CI Integration

The test runner returns appropriate exit codes:
- `0`: All tests passed
- `1`: One or more tests failed or no tests run

Example CI usage:
```bash
./tests/run_all_tests.py || exit 1
```

## Troubleshooting

### "HelloWorld binary not found"

Build the example project:
```bash
cd examples/HelloWorld && xcodebuild
```

### "IDSService not found"

The IDS.framework may not be available on all systems. Tests handle this
gracefully by reporting the framework as unavailable rather than failing.

### Tests timing out

Increase timeout in the test or use `--quick` for faster subset:
```bash
./tests/run_all_tests.py --quick
```

### Verbose debugging

Use `--verbose` to see full LLDB output:
```bash
./tests/run_all_tests.py --verbose obrk
```
