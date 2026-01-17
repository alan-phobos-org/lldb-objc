# Claude Code Guidelines for lldb-objc

## Project Overview

lldb-objc provides LLDB Python scripts for enhanced Objective-C debugging, including the `obrk` command for setting breakpoints on Objective-C methods.

## Key Files

- `scripts/objc_breakpoint.py` - The `obrk` command implementation
- `scripts/objc_dump.py` - The `odump` command for dumping NSData/memory to files
- `scripts/objc_utils.py` - Utility functions for method resolution
- `scripts/objc_core.py` - Core parsing and formatting functions
- `tests/test_obrk.py` - Comprehensive test suite for breakpoint functionality
- `tests/test_odump.py` - Test suite for odump command

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

**Key insight**: If `b <addr>` works but `obrk` fails with the same address, the problem is in how the breakpoint is created, not the environment.

**Root cause**: Going through `SBAddress` at all can cause issues. The `class_getMethodImplementation()` runtime call returns a load address directly - we should use that raw address without any intermediate transformations.

### The Fix

1. Use the raw IMP address directly from `class_getMethodImplementation()`:
```python
# resolve_method_address now returns raw_imp_addr as the last element
resolved_addr, class_ptr, sel_ptr, error, raw_imp_addr = resolve_method_address(...)
load_addr = raw_imp_addr  # Use this directly, not resolved_addr.GetLoadAddress()
```

2. Use `HandleCommand` with `breakpoint set -a` to ensure exact CLI parity:
```python
cmd = f"breakpoint set -a 0x{load_addr:x} -N '{method_name}'"
interpreter.HandleCommand(cmd, cmd_result)
```

### Debugging with --verbose

Use `obrk --verbose -[Class method]` or `obrk -v -[Class method]` to see detailed debug output:
- Target/process state
- Raw IMP address vs SBAddress comparison
- Module/section info
- Exact command being executed

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
