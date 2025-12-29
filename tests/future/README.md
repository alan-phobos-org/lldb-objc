# Future Feature Tests

This directory contains test suites for features that are planned but not yet implemented.

## Tests in this directory

| Test File | Feature | Status |
|-----------|---------|--------|
| `test_osel_perf.py` | `osel` performance optimization | Planned |

## Running these tests

These tests are **not** run by the standard test runner. They will fail until
the corresponding features are implemented.

To run them manually:
```bash
# Run a specific future test
python3 tests/future/test_osel_perf.py
```

## When to move tests back

Once a feature is implemented:
1. Move the test file from `tests/future/` to `tests/`
2. Update `tests/run_all_tests.py` to include it in the standard test suite
3. Update this README

## Test specifications

These test files serve as specifications for the features. They document:
- Expected command syntax
- Expected output formats
- Error handling requirements
- Edge cases to consider

Review these tests before implementing the corresponding feature.
