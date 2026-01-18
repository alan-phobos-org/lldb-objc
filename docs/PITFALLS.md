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

### LLDB Block Expressions: for-in Loops Don't Work
Use index-based iteration inside LLDB block expressions. `for-in` causes warnings and may fail.

```objc
// WRONG - for-in generates warnings, may fail
for (NSString *path in paths) { ... }

// RIGHT - index-based iteration
for (NSUInteger i = 0; i < [paths count]; i++) {
    NSString *path = paths[i];
    ...
}
```

### LLDB Blocks: Cast Function Return Types
Functions called inside LLDB blocks need explicit return type casts.

```objc
// WRONG - 'access' has unknown return type error
int result = access([path UTF8String], 2);

// RIGHT - explicit cast
int result = (int)access([path UTF8String], 2);
```

### NSNumber Boolean Parsing
`GetValueAsUnsigned()` returns the NSNumber *pointer address*, not the boolean value. Use `GetSummary()` which returns "YES" or "NO".

```python
# WRONG - returns pointer address like 8803572976
child.GetValueAsUnsigned()

# RIGHT - returns "YES" or "NO"
child.GetSummary()  # "YES" or "NO"
is_true = child.GetSummary() == "YES"
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

### iOS System Binary Breakpoint Errors

**Problem**: Setting breakpoints on iOS system binaries may fail with "error 9 sending breakpoint request" even when `b <addr>` works with the same address.

**Root cause**: Going through `SBAddress` at all can cause issues with iOS shared cache binaries. The `class_getMethodImplementation()` runtime call returns a load address directly - use that raw address without intermediate transformations.

**The fix**: Use the raw IMP address directly from `class_getMethodImplementation()`:

```python
# resolve_method_address now returns raw_imp_addr as the last element
resolved_addr, class_ptr, sel_ptr, error, raw_imp_addr = resolve_method_address(...)
load_addr = raw_imp_addr  # Use this directly, not resolved_addr.GetLoadAddress()
```

Use `HandleCommand` with `breakpoint set -a` to ensure exact CLI parity:

```python
cmd = f"breakpoint set -a 0x{load_addr:x} -N '{method_name}'"
interpreter.HandleCommand(cmd, cmd_result)
```

**Debugging**: Use `obrk --verbose -[Class method]` or `obrk -v -[Class method]` to see detailed debug output including target/process state, raw IMP vs SBAddress comparison, module/section info, and the exact command being executed.

See [IOS_BREAKPOINT_ERRORS_DESIGN.md](IOS_BREAKPOINT_ERRORS_DESIGN.md) for detailed analysis of code signing, hardware breakpoints, and environment-specific workarounds.

### Data Extraction from ObjC Objects
When extracting data from Objective-C objects in LLDB:

```python
# NSData - call runtime methods, then read memory
bytes_ptr = evaluate_expression(frame, "[obj bytes]").GetValueAsUnsigned()
length = evaluate_expression(frame, "[obj length]").GetValueAsUnsigned()
data = process.ReadMemory(bytes_ptr, length, error)

# NSDictionary - get keys array, iterate with GetChildAtIndex()
keys = evaluate_expression(frame, "[dict allKeys]")
for i in range(keys.GetNumChildren()):
    key = keys.GetChildAtIndex(i)

# NSString - use GetSummary() and strip outer quotes
s = value.GetSummary()[1:-1]  # "hello" -> hello

# NSNumber - GetValueAsUnsigned() returns pointer, use GetSummary()
is_true = value.GetSummary() == "YES"  # for booleans

# Always include fallback for robustness
obj_desc = evaluate_expression(frame, f"[{addr} description]")

# Limit iteration to prevent hangs
MAX_ITEMS = 50
for i in range(min(count, MAX_ITEMS)):
    # ... process items
```

**Key points:**
- Call runtime methods to get pointers/counts, then use `ReadMemory()` for bulk data
- `GetSummary()` returns user-friendly strings for NSString, NSNumber, etc.
- Always check validity and handle errors before dereferencing
- Limit iterations to prevent infinite loops or timeouts

### Keychain Access and Authorization Prompts

**Problem**: Calling `SecItemCopyMatching()` via LLDB expression evaluation can trigger macOS keychain authorization prompts. When the prompt appears, the process receives SIGSTOP, causing LLDB expression evaluation to fail with "Execution was interrupted, reason: signal SIGSTOP".

**Why it happens**:
- macOS Security framework requires user authorization for sensitive keychain items
- Authorization prompts pause the target process with SIGSTOP
- LLDB's expression evaluator can't handle unexpected process stops
- System processes (e.g., `identityservicesd`) have stricter keychain access controls

**The fix**: Use `kSecUseAuthenticationUISkip` in keychain queries to suppress authorization prompts:

```objc
NSMutableDictionary *query = [NSMutableDictionary dictionary];
query[(id)kSecClass] = (id)kSecClassGenericPassword;
query[(id)kSecReturnAttributes] = @YES;
query[(id)kSecReturnData] = @YES;
query[(id)kSecMatchLimit] = (id)kSecMatchLimitAll;
query[(id)kSecUseAuthenticationUI] = (id)kSecUseAuthenticationUISkip;  // Critical!

CFTypeRef result = NULL;
OSStatus status = SecItemCopyMatching((CFDictionaryRef)query, &result);
```

**Implications**:
- Only keychain items accessible without user authentication will be returned
- Items requiring authentication will be silently skipped
- This is expected behavior when debugging - use `oentitlements` to verify the process has appropriate keychain access entitlements

**Alternatives**:
- `kSecUseAuthenticationUIFail` - Fail immediately if auth required (returns errSecInteractionNotAllowed)
- `kSecUseAuthenticationUIAllow` - Default behavior, shows prompts (causes SIGSTOP in LLDB)

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

### Development Workflow: Run ./install.py After Changes
LLDB loads Python modules at startup from the installed location. After modifying source files:

```bash
./install.py  # Copy scripts to ~/.lldb/lldb-objc/
```

Then start a fresh LLDB session. The `oreload` command may not fully reload due to Python module caching. For guaranteed testing of changes:

```bash
# Use --no-lldbinit to avoid cached modules
lldb --no-lldbinit
(lldb) command script import /path/to/scripts/your_module.py
```

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

### sandbox_init() Detection - Use access() not sandbox_check()

Binaries that opt into a sandbox via `sandbox_init()` require special handling:

1. **NSFileManager doesn't respect sandbox restrictions**: `isWritableFileAtPath:` checks Unix file permissions only, not sandbox policy.

2. **sandbox_check() always returns "denied" from LLDB**: When called via LLDB expression evaluation, `sandbox_check()` always returns 1 (denied) regardless of actual sandbox policy - even for paths the sandbox allows.

3. **access() works correctly**: The `access(path, W_OK)` system call properly respects `sandbox_init()` restrictions when called from LLDB.

```c
// From LLDB expression - sandbox_check BROKEN:
(lldb) expr (int)sandbox_check((pid_t)getpid(), "file-write-data", 1, "/tmp")
(int) $0 = 1  // WRONG - says denied even when /tmp is allowed!

// From LLDB expression - access() WORKS:
(lldb) expr (int)access("/tmp", 2)  // W_OK = 2
(int) $0 = 0  // CORRECT - allowed

(lldb) expr (int)access("/var", 2)
(int) $0 = -1  // CORRECT - denied
```

**Solution implemented in osbx**: Use `access(path, W_OK)` for both sandbox detection and path writability checks. This correctly handles both App Sandbox and `sandbox_init()` sandboxes.

See `examples/HelloWorld-Sandboxed/` for a test binary.

### SBPL Profile Syntax: deny-default vs allow-default

When writing custom sandbox profiles with SBPL (Sandbox Profile Language), **avoid `(deny default)`** as the base policy.

**Problem**: `(deny default)` requires explicitly allowing every single operation the process needs - mach ports, signals, syscalls, IPC, shared memory, etc. Missing any operation causes cryptic failures (e.g., error code 5683 with no error message).

```c
// WRONG - requires enumerating every operation
static const char *PROFILE =
    "(version 1)\n"
    "(deny default)\n"
    "(allow process*)\n"       // process* isn't valid
    "(allow mach*)\n"          // mach* isn't valid
    "(allow system*)\n"        // system* isn't valid
    // ... will fail with unhelpful error
```

**Solution**: Use `(allow default)` and selectively deny what you want to restrict. Later rules override earlier ones.

```c
// RIGHT - start permissive, restrict specific things
static const char *PROFILE =
    "(version 1)\n"
    "(allow default)\n"        // allow everything first
    "(deny network*)\n"        // block network
    "(deny file-write*)\n"     // block all writes
    "(allow file-write* (subpath \"/private/tmp\"))\n"  // whitelist
    "(allow file-write* (subpath \"/tmp\"))\n"
    "(allow file-write* (subpath \"/dev\"))\n";
```

**Key points**:
- Operation wildcards like `process*`, `mach*`, `system*` are often invalid
- SBPL requires specific operation names: `mach-lookup`, `process-exec`, `signal`, etc.
- Rule order matters - later rules override earlier ones
- Use builtin profiles (e.g., `"no-network"` with `SANDBOX_NAMED_BUILTIN`) as a simpler alternative when possible
