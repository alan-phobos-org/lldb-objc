# Common Pitfalls

Technical gotchas and lessons learned from lldb-objc development.

**Read this file when:** debugging failures, implementing new commands, or investigating unexpected behavior.

---

## LLDB API Gotchas

### String Handling
Use `s[1:-1]` not `strip('"')` for LLDB `GetSummary()` strings.

```python
# WRONG - removes multiple quotes
value.GetSummary().strip('"')  # "hello"" → hello

# RIGHT - removes exactly outer quotes
value.GetSummary()[1:-1]  # "hello" → hello
```

### F-strings with Objective-C Blocks
Use `^{{` and `}}` for Objective-C blocks in f-strings to escape the braces.

```python
# WRONG
f"(void)^{ ... }"  # Python interprets { as f-string

# RIGHT
f"(void)^{{ ... }}"  # Escapes to literal ^{
```

### ASLR/Address Handling
Always use `SBAddress` for breakpoints, never raw ints.

```python
# WRONG - may fail on iOS with aggressive ASLR
target.BreakpointCreateByAddress(imp_int)

# RIGHT - properly handles ASLR
sbaddr = target.ResolveLoadAddress(imp)
target.BreakpointCreateBySBAddress(sbaddr)
```

Load addresses from runtime (e.g., `class_getMethodImplementation()`) are already ASLR-adjusted.

### API Validation
Verify LLDB methods exist before using:

```bash
lldb -b -o "script help(lldb.SBTarget.MethodName)"
```

Check signatures with `help()`, inspect available methods with `dir()`. Test in isolation before integrating.

---

## Code Organization

### Function Signature Changes
When changing return types (e.g., `int` → `SBAddress`), grep for all callers and update them atomically in one change.

### Import Locations
Pure Python utilities belong in `objc_core.py` (e.g., `unquote_string`, `extract_category_from_symbol`). Import from the correct module - don't assume re-exports exist.

### Caching with Filter Flags
When caching data, ensure partial queries (e.g., `--instance` only) don't corrupt the cache for full queries. Either skip caching, or always fetch complete data and filter at display time.

### Memory Allocation Cleanup
When allocating memory via `malloc()`, ensure cleanup happens even on exceptions:

```python
try:
    addr = frame.EvaluateExpression("(void*)malloc(1024)")
    # ... use memory ...
finally:
    frame.EvaluateExpression(f"free({addr})")
```

---

## Testing Pitfalls

### Platform Differences
- iOS has more aggressive ASLR than macOS
- Some frameworks load differently between platforms
- Simulator vs device may have different class availability
- Bugs may only manifest on iOS - test platform-specific edge cases

### Test Quality
- If manual testing reveals a bug that tests missed, improve the test framework
- Tests passing is necessary but not sufficient - manually verify in actual LLDB session
- Test infrastructure itself needs validation (e.g., ensure it catches tracebacks)

### Root Cause Analysis
When something unexpected happens (tests pass but code fails):
1. Fix the immediate bug
2. Investigate why tests didn't catch it
3. Improve test framework to catch this class of errors
4. Ask "why" multiple times - don't stop at surface fixes

---

## Output Formatting

### No Duplicate Information
Each piece of information should appear exactly once in the most appropriate location. When multiple sources provide the same data (e.g., type info from both value description and type decoding), choose the most user-friendly presentation.

### Color Conventions
- Primary info: normal text (class name, method name)
- Secondary info: dim gray `\033[90m...\033[0m` (types, hierarchy, attributes)

### Verify After Changes
After changes that affect user-facing output, manually inspect results for:
- Duplicate or redundant information
- Consistent alignment and spacing
- Proper use of color codes
- Appropriate truncation of long values

---

## Performance Notes

### Expression Evaluation
`frame.EvaluateExpression()` is slow (10-50ms) - minimize calls.

### Memory Reading
`process.ReadMemory()` is fast (<1ms) - use for bulk data.

### Batch Size
Optimal batch size for class enumeration: **35** classes per `EvaluateExpression()` call.

### Caching
- Per-process caching: first run ~12s, cached <0.01s
- Cache invalidated on `--reload`, process restart, or framework load

---

## Sandbox Command (osbx)

### fnmatch Behavior
Python's `fnmatch` treats `*` differently than shell globbing - it **matches `/` characters**. This is more permissive than expected.

```python
# fnmatch behavior (Python)
fnmatch.fnmatch("/tmp/foo/bar", "/tmp/*")  # True (unexpected)

# Shell glob behavior
# /tmp/* would NOT match /tmp/foo/bar
```

If you need strict single-directory matching, use regex or implement custom logic.

### Platform Detection
The target triple alone isn't sufficient to distinguish iOS from macOS on Apple Silicon:
- `arm64-apple-darwin` could be either iOS device or Apple Silicon Mac
- Disambiguate by checking `NSHomeDirectory()` patterns:
  - `/var/mobile/` → iOS
  - `/Users/` → macOS
  - `/Library/Containers/` → macOS (sandboxed app)

### Operator Precedence
Watch for `or`/`and` precedence issues in conditions:

```python
# WRONG - and binds tighter than or
if path.startswith("/System") or path.startswith("/usr/") and not path.startswith("/usr/local"):

# RIGHT - explicit parentheses
if path.startswith("/System") or (path.startswith("/usr/") and not path.startswith("/usr/local")):
```

### Directory Enumeration Performance
When enumerating directories in thorough mode:
- Limit entries per directory (`MAX_ENTRIES_PER_DIR = 100`) to prevent explosion
- Check if directory is readable before attempting enumeration
- Track visited paths to avoid symlink loops
- Use breadth-first expansion with depth limits
