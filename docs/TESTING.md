# Testing Guide

Comprehensive testing documentation for LLDB Objective-C Tools.

## Quick Start

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Unit tests (fast, no LLDB required)
pytest

# Integration tests (requires macOS + LLDB)
./build.sh test-quick    # Quick subset
./build.sh test-int      # Full suite

# All tests
./build.sh test-all

# Full pre-commit check
./build.sh check
```

## Test Architecture

```
┌─────────────────────────────────────────┐
│ Unit Tests (pytest)                     │
│ - Pure Python logic in objc_core.py     │
│ - Fast (<0.1s total)                    │
│ - Cross-platform (Linux OK)             │
│ - Run: pytest                           │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│ Integration Tests                        │
│ - Full LLDB commands                    │
│ - Shared session (15-25s vs 120s)       │
│ - macOS-only                            │
│ - Run: ./tests/run_all_tests.py         │
└─────────────────────────────────────────┘
```

## Directory Structure

```
tests/
├── run_all_tests.py      # Unified test runner
├── test_helpers.py       # Shared infrastructure + Validators
├── test_obrk.py          # obrk command tests
├── test_ocls.py          # ocls command tests
├── test_osel.py          # osel command tests
├── test_ocall.py         # ocall command tests
├── test_owatch.py        # owatch command tests
├── test_opool.py         # opool command tests
├── test_oinstance.py     # oinstance command tests
├── test_odump.py         # odump command tests
├── test_oentitlements.py # oentitlements command tests
├── test_okeychain.py     # okeychain command tests
├── test_osc.py           # osc command tests (shared cache)
├── test_osc_unit.py      # osc unit tests with mocking
├── test_hierarchy.py     # Class hierarchy display tests
├── test_ivars_props.py   # --ivars/--properties tests
├── test_osel_perf.py     # osel performance tests
├── test_timing.py        # Performance timing tests
├── test_bootstrap.py     # Interactive LLDB setup
├── test_osbx.py          # osbx command tests
├── test_osbx_sandboxed.py # osbx tests with sandboxed binary
├── test_smoke.py         # Quick smoke tests
└── unit/
    ├── test_objc_core.py # objc_core.py tests
    ├── test_objc_sandbox.py # sandbox utilities tests
    └── README.md
```

## Unit Tests

### What They Test

Pure Python logic that doesn't require LLDB:

| Module | Functions | Test Count |
|--------|-----------|------------|
| `objc_core.py` | `parse_method_signature()`, `format_method_name()`, `unquote_string()` | ~43 |
| Future | `pattern_to_regex()`, `parse_property_attributes()` | Planned |

### Running Unit Tests

```bash
# All unit tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/unit/test_objc_core.py

# Specific test class
pytest tests/unit/test_objc_core.py::TestParseMethodSignature

# With coverage
pytest --cov=scripts --cov-report=html

# By marker
pytest -m parsing
pytest -m formatting
```

### Test Markers

```python
@pytest.mark.parsing      # String/regex parsing
@pytest.mark.formatting   # Output formatting
@pytest.mark.pattern      # Pattern matching
@pytest.mark.utils        # General utilities
```

## Integration Tests

### Prerequisites

Build the HelloWorld example binary:

```bash
cd examples/HelloWorld && xcodebuild
```

### Running Integration Tests

```bash
# All suites
./tests/run_all_tests.py

# Quick subset (faster)
./tests/run_all_tests.py --quick

# Specific suites
./tests/run_all_tests.py obrk ocls

# Performance tests
./tests/run_all_tests.py --perf

# Verbose output
./tests/run_all_tests.py --verbose
```

### Test Suites

| Suite | File | Tests | Description |
|-------|------|-------|-------------|
| `obrk` | `test_obrk.py` | 14 | Breakpoint command |
| `ocls` | `test_ocls.py` | 23 | Class finder |
| `osel` | `test_osel.py` | 18 | Selector finder |
| `ocall` | `test_ocall.py` | 9 | Method caller |
| `owatch` | `test_owatch.py` | 8 | Method watcher |
| `hierarchy` | `test_hierarchy.py` | 7 | Hierarchy display |
| `ivars_props` | `test_ivars_props.py` | 13 | Ivars/properties |
| `osbx` | `test_osbx.py` | - | Sandbox scanner (basic) |
| `osbx_sandboxed` | `test_osbx_sandboxed.py` | - | Sandbox scanner (sandboxed binary) |

### Sandbox Tests

The `test_osbx_sandboxed.py` test uses a special sandboxed binary that opts into a restrictive sandbox via `sandbox_init()`. This demonstrates sandbox detection limitations:

```bash
# Build the sandboxed test binary
cd examples/HelloWorld-Sandboxed && make

# Run the sandbox test
python3 tests/test_osbx_sandboxed.py
```

**Important**: Due to how LLDB expression evaluation works, `sandbox_init()` sandboxes cannot be fully detected by osbx. The test validates that osbx runs correctly and produces valid output, but `sandbox_active` will be `false`. See [PITFALLS.md](PITFALLS.md) for details.

### Output Format (Pytest-Style)

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

With failures:
```
======================================================================
FAILURES
======================================================================

______________________________________________________________________
ocall :: Instance method from variable
______________________________________________________________________

Command failed
  Expected: 'TestString' in output
  Actual: Error encountered

  Output (first 500 chars):
  error: Method call failed...

  Re-run this suite: python3 tests/test_ocall.py

======================================================================
1 failed, 8 passed in 12.40s
======================================================================
```

## Writing Tests

### Unit Test Template

```python
import pytest
from scripts.objc_core import parse_method_signature

class TestParseMethodSignature:
    def test_instance_method(self):
        is_inst, cls, sel, err = parse_method_signature('-[NSString length]')
        assert is_inst == True
        assert cls == 'NSString'
        assert sel == 'length'
        assert err is None

    def test_invalid_input(self):
        is_inst, cls, sel, err = parse_method_signature('invalid')
        assert err is not None
```

### Integration Test Template

```python
from test_helpers import run_lldb_test, TestResult, run_test_suite, Validators

def test_my_feature():
    """Test description."""
    test = TestResult("My Feature Test")

    stdout, stderr, _ = run_lldb_test(
        ['my_command arg1'],
        scripts=['my_script.py'],
        timeout=30
    )
    output = stdout + stderr

    if 'expected' in output:
        test.pass_("Works correctly")
    else:
        test.fail(f"Unexpected: {output[:200]}")

    return test

def main():
    tests = [test_my_feature]
    passed, total = run_test_suite("MY TEST SUITE", tests)
    sys.exit(0 if passed == total else 1)
```

### Validator Utilities

Pre-built validators for common patterns:

```python
from test_helpers import Validators

# Simple checks
Validators.contains('NSString')
Validators.contains_any('error', 'failed', 'not found')
Validators.contains_all('Class:', 'SEL:', 'IMP:')
Validators.regex_match(r'\d+ classes found')

# Specialized
Validators.breakpoint_created()  # Checks for 'Breakpoint #' and 'IMP:'
Validators.error_reported()      # Checks for error/usage message

# Combining
Validators.combine_and(
    Validators.contains_all('Class:', 'SEL:'),
    Validators.breakpoint_created()
)

# Custom logic
Validators.custom(
    lambda o: len(o) > 100,
    pass_msg="Long output received",
    fail_msg="Output too short"
)
```

## Test Helpers API

```python
# Run LLDB with commands
stdout, stderr, returncode = run_lldb_test(
    commands=['ocls NSString'],
    scripts=['objc_cls.py'],
    timeout=30,
    load_ids_framework=True
)

# Track test results
result = TestResult("Test Name")
result.pass_("Success message")
result.fail("Failure reason")
result.metrics = {'time': 1.23}

# Run test suite
passed, total = run_test_suite(
    "SUITE NAME",
    [test_func1, test_func2]
)
```

## Best Practices

### Development Workflow

1. **During development**: Run `pytest` frequently
2. **Before committing**: Run `./build.sh check`
3. **Before merging**: Run full integration suite
4. **In CI**: Run `pytest` (Linux OK)

### Test Quality

- **Don't trust tests blindly**: Manual verification is still needed
- **Test the test framework**: Ensure it catches errors properly
- **Investigate unexpected outcomes**: If tests pass but code fails, improve tests

### Common Issues

**"HelloWorld binary not found"**
```bash
cd examples/HelloWorld && xcodebuild
```

**"CSSymbol not found"**
The CoreSymbolication.framework may not be available. Tests handle this gracefully.

**Tests timing out**
```bash
./tests/run_all_tests.py --quick
```

**Interactive debugging**
```bash
python3 tests/test_bootstrap.py
```

## Code Organization

### Testability Layers

```
┌────────────────────┐     ┌────────────────────┐
│    objc_core.py    │     │   objc_utils.py    │
├────────────────────┤     ├────────────────────┤
│ Pure Python logic  │     │ LLDB-dependent ops │
│ - Parsing          │ ←── │ - Runtime queries  │
│ - Formatting       │     │ - Expression eval  │
│ - Pattern matching │     │ - Memory reading   │
│ Unit testable      │     │ Integration tested │
└────────────────────┘     └────────────────────┘
```

### Extracting Testable Logic

Good candidates for extraction:

| Function | Location | Test Type |
|----------|----------|-----------|
| `parse_method_signature()` | objc_core.py | Unit |
| `format_method_name()` | objc_core.py | Unit |
| `pattern_to_regex()` | (extract from commands) | Unit |
| `resolve_method_address()` | objc_utils.py | Integration |

## CI/CD Integration

Unit tests can run on Linux:

```yaml
# .github/workflows/test.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements-dev.txt
      - run: pytest
```

Integration tests require macOS (self-hosted runner or manual).

## Performance Benchmarks

### Test Execution Time

| Test Type | Time | Notes |
|-----------|------|-------|
| Unit tests | <0.1s | Fast feedback |
| Quick integration | ~60s | 3 suites |
| Full integration | ~3 min | All suites |

### Shared Session Optimization

Without shared session: ~120s (each test launches LLDB)
With shared session: ~15-25s (single LLDB instance)

## Troubleshooting

### Debug Output

```bash
# Verbose integration tests
./tests/run_all_tests.py --verbose

# Single suite with output
python3 tests/test_obrk.py
```

### Manual LLDB Testing

```bash
lldb -b -o "command script import scripts" \
     -o "ocls NSString" \
     examples/HelloWorld/HelloWorld
```

### Check Test Framework

```python
# Verify validators work
from test_helpers import Validators
v = Validators.contains('test')
print(v('this is a test'))  # (True, 'Found...')
print(v('no match'))        # (False, 'Expected...')
```
