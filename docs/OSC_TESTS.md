# OSC Command Test Suite

Comprehensive test suite for the `osc` (Objective-C Shared Cache) command.

## Overview

The test suite validates that `osc` correctly reports dyld shared cache information and that all reported addresses match a valid cache slide.

## Test Structure

### 1. Unit Tests ([test_osc_unit.py](../tests/test_osc_unit.py))

Pure Python unit tests that mock LLDB objects to test the `get_shared_cache_info()` function in isolation.

**What they test:**
- Successful retrieval of all cache information fields
- Handling of processes without shared cache
- Expression evaluation failures
- Address alignment (16KB page alignment)
- Address consistency (end = base + size)
- UUID format validation
- Verbose mode functionality

**Run:**
```bash
python3 tests/test_osc_unit.py
```

**Test count:** 7 unit tests

### 2. Integration Tests ([test_osc.py](../tests/test_osc.py))

Integration tests that run `osc` command in a real LLDB session and validate output.

**What they test:**
- Basic shared cache information display
- Address validation:
  - Base address is page-aligned (16KB = 0x4000)
  - Base address is in reasonable range (> 4GB for modern systems)
  - Size is reasonable (100MB - 10GB)
  - End address equals base + size
- Cache slide validation:
  - ASLR slide message is present
  - Loaded address is properly aligned
- UUID format validation (8-4-4-4-12 format)
- File path validation
- Verbose mode (`--verbose` and `-v` flags)
- Comprehensive validation (all checks together)

**Run:**
```bash
python3 tests/test_osc.py
```

**Test count:** 9 integration tests

### 3. Smoke Tests ([test_smoke.py](../tests/test_smoke.py))

Quick validation that `osc` runs and produces basic output as part of the full smoke test suite.

**Run:**
```bash
sudo python3 tests/test_smoke.py
```

## Cache Slide Validation

The tests verify that the shared cache has a valid ASLR slide by checking:

1. **Page Alignment**: Base address must be aligned to page boundaries (16KB on modern macOS)
   ```
   base % 0x4000 == 0
   ```

2. **Valid Memory Range**: Base address should be in high memory (> 4GB)
   ```
   base >= 0x100000000
   ```

3. **Address Consistency**: End address must equal base + size
   ```
   end == base + size
   ```

4. **Reasonable Size**: Size should be between 100MB and 10GB
   ```
   100MB <= size <= 10GB
   ```

5. **ASLR Message**: Output includes "with ASLR slide applied"

## Test Validators

The integration tests use specialized validators from [test_osc.py](../tests/test_osc.py):

| Validator | Purpose |
|-----------|---------|
| `validate_shared_cache_info()` | Checks for basic output fields |
| `validate_cache_addresses()` | Validates addresses are correct and consistent |
| `validate_cache_slide()` | Verifies ASLR slide message and alignment |
| `validate_uuid_format()` | Checks UUID is properly formatted |
| `validate_file_path()` | Validates file path is present |
| `validate_verbose_output()` | Checks for debug output in verbose mode |
| `combine_validators()` | Combines multiple validators (all must pass) |

## Helper Functions

The integration tests include helper functions to extract data from output:

- `extract_hex_value(output, field_name)` - Extract hex address for a field
- `extract_size_bytes(output)` - Extract size in bytes
- `extract_uuid(output)` - Extract UUID string

## Running Tests

### Run all osc tests

```bash
# Unit tests
python3 tests/test_osc_unit.py

# Integration tests
python3 tests/test_osc.py

# As part of full test suite
./tests/run_all_tests.py
```

### Run via build script

```bash
# Quick tests
./build.sh test-quick

# All integration tests
./build.sh test-int

# All tests (unit + integration)
./build.sh test-all
```

## Example Output

### Successful Integration Test

```
======================================================================
test session starts
platform darwin -- Python 3.11.7
collected 9 items

......... [100%]

======================================================================
9 passed in 2.45s
======================================================================
```

### Successful Unit Test

```
test_successful_cache_info_with_all_fields (__main__.TestGetSharedCacheInfo) ... ok
test_no_shared_cache_available (__main__.TestGetSharedCacheInfo) ... ok
test_expression_evaluation_failure (__main__.TestGetSharedCacheInfo) ... ok
test_address_alignment (__main__.TestGetSharedCacheInfo) ... ok
test_address_consistency (__main__.TestGetSharedCacheInfo) ... ok
test_uuid_format (__main__.TestGetSharedCacheInfo) ... ok
test_verbose_mode (__main__.TestGetSharedCacheInfo) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.012s

OK
```

## Implementation Details

### What osc Reports

- **Base Address**: Start address of shared cache in memory (with ASLR)
- **End Address**: End address (base + size)
- **Size**: Total size of shared cache (formatted as GB/MB/KB)
- **UUID**: Build UUID of the shared cache
- **File Path**: Path to shared cache file on disk
- **Loaded Address**: Base address with note about ASLR slide

### Test Coverage

| Feature | Unit Test | Integration Test | Smoke Test |
|---------|-----------|------------------|------------|
| Basic output | ✓ | ✓ | ✓ |
| Address validation | ✓ | ✓ | - |
| Cache slide validation | ✓ | ✓ | - |
| UUID format | ✓ | ✓ | - |
| File path | ✓ | ✓ | - |
| Verbose mode | ✓ | ✓ | - |
| Error handling | ✓ | - | - |
| No cache case | ✓ | - | - |

## Notes

- Integration tests require a built HelloWorld binary (`examples/HelloWorld/HelloWorld/HelloWorld`)
- Smoke tests require sudo to attach to system processes
- Unit tests can run on any platform with Python 3
- Integration tests require macOS with LLDB

## See Also

- [TESTING.md](TESTING.md) - General testing guide
- [test_helpers.py](../tests/test_helpers.py) - Shared test infrastructure
- [objc_sharedcache.py](../scripts/objc_sharedcache.py) - Implementation
