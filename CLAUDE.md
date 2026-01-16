# Claude Code Guidelines for lldb-objc

## Project Overview

lldb-objc provides LLDB Python scripts for enhanced Objective-C debugging, including the `obrk` command for setting breakpoints on Objective-C methods.

## Key Files

- `scripts/objc_breakpoint.py` - The `obrk` command implementation
- `scripts/objc_utils.py` - Utility functions for method resolution
- `scripts/objc_core.py` - Core parsing and formatting functions
- `tests/test_obrk.py` - Comprehensive test suite for breakpoint functionality

## Important Patterns

### LLDB Expression Evaluation
- Use unique variable prefixes (e.g., `s_img_count`) to avoid symbol conflicts
- Check both `result.IsValid()` and `result.GetError().Fail()`
- Complex block expressions can timeout; prefer multiple simple expressions
- Use direct memory reads (`process.ReadMemory`) when possible

### Breakpoint Timing
- ObjC runtime must be fully initialized before using runtime functions
- Stopping at `--stop-at-entry` or early dyld points will cause failures
- HelloWorld examples use `SIGTRAP` to ensure runtime is ready

## iOS System Binary Debugging Issues

### The "error 9 sending breakpoint request" Problem

**Root cause**: Using `BreakpointCreateBySBAddress(SBAddress)` instead of `BreakpointCreateByAddress(uint64_t)`.

The `SBAddress` includes section-relative context that can cause the GDB remote protocol packet to be malformed for iOS shared cache binaries. Using the raw load address (like `b <addr>` does) bypasses this issue.

**Key insight**: If `b <addr>` works but `obrk` fails with the same address, the problem is in how the breakpoint is created, not the environment.

### The Fix

```python
# Wrong - includes section context that can cause issues:
breakpoint = target.BreakpointCreateBySBAddress(resolved_addr)

# Correct - matches `b <addr>` behavior:
load_addr = resolved_addr.GetLoadAddress(target)
breakpoint = target.BreakpointCreateByAddress(load_addr)
```

See `docs/IOS_BREAKPOINT_ERRORS_DESIGN.md` for detailed analysis.

## Testing

Run tests with:
```bash
python tests/test_obrk.py
```

Tests use shared LLDB sessions for performance. The HelloWorld examples in `examples/` are used as test targets.

## Code Style

- Type hints for all function signatures
- Docstrings for public functions
- Guard against double initialization in `__lldb_init_module`
- Use `from __future__ import annotations` for forward references
