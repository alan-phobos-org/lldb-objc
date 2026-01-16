# Debugging LLDB Python Scripts

Lessons learned from debugging the lldb-objc Python scripts.

## Testing Changes in LLDB

### Module Caching Problem

LLDB caches Python modules. If you have lldb-objc installed (via `.lldbinit`), your changes won't take effect even after `command script import`.

**Solutions:**

1. **Use `oreload`** - Reloads all command modules:
   ```
   (lldb) oreload
   ```

2. **Use `--no-lldbinit`** - Skip auto-loading entirely:
   ```bash
   lldb --no-lldbinit -s commands.lldb
   ```

3. **Fresh LLDB session** - Quit and restart LLDB

### Breakpoint Timing Matters

**Problem:** Stopping too early (e.g., in dyld or libobjc initialization) means the Objective-C runtime isn't fully initialized. Runtime functions like `objc_copyImageNames` or `objc_copyClassNamesForImage` may return empty or fail.

**Good breakpoints:**
- After `main()` has started executing
- On application-specific methods
- On `SIGTRAP` raised by the app itself (like HelloWorld-Optimised does)

**Bad breakpoints:**
- `objc_autoreleasePoolPush` (too early - inside dyld)
- `--stop-at-entry` (before dyld finishes loading)

**Example - HelloWorld-Optimised uses SIGTRAP:**
```objc
// In main.m - raises SIGTRAP after runtime is ready
(void)signal(SIGTRAP, SIG_IGN); raise(SIGTRAP); (void)signal(SIGTRAP, SIG_DFL);
```

## Expression Evaluation Pitfalls

### Complex Block Expressions Timeout

**Problem:** Large block expressions with loops can timeout or fail silently in LLDB.

**Bad - times out:**
```c
(void *)(^{
    for (int i = 0; i < count; i++) {
        // Loop with string operations
        total_len += strlen(names[i]) + 1;
    }
    // More loops...
}())
```

**Good - multiple simple expressions:**
```python
# Step 1: Get pointer (simple expression)
expr = "(void *)(^{ ... return (void *)ptr; }())"
ptr = evaluate_expression(frame, expr).GetValueAsUnsigned()

# Step 2: Get count (separate simple expression)
count = evaluate_expression(frame, count_expr).GetValueAsUnsigned()

# Step 3: Read memory directly (no expression needed)
data = process.ReadMemory(ptr, count * 8, error)

# Step 4: Read strings directly
for str_ptr in pointers:
    name = process.ReadCStringFromMemory(str_ptr, 256, error)
```

### Symbol Name Conflicts

**Problem:** Variable names in expressions can conflict with symbols in the target process. Common names like `count`, `names`, `offset` cause ambiguous resolution.

**Bad:**
```c
unsigned int count = 0;  // Conflicts with symbols named "count"
const char **names = objc_copyImageNames(&count);  // Ambiguous
```

**Good - use unique prefixes:**
```c
unsigned int s_img_count = 0;
const char **s_img_names = objc_copyImageNames(&s_img_count);
```

### Expression Result Checking

Always check both validity AND error status:

```python
result = evaluate_expression(frame, expr)

# Both checks are necessary
if not result.IsValid() or result.GetError().Fail():
    return []

ptr = result.GetValueAsUnsigned()
if ptr == 0:
    return []
```

## Debug Output Strategy

### Print Statements May Not Show

If module is cached, new print statements won't execute. Use `--no-lldbinit` or `oreload`.

### Useful Debug Pattern

```python
def my_function(frame, timing):
    print(f"DEBUG: Entering function")

    result = evaluate_expression(frame, expr)
    print(f"DEBUG: result.IsValid()={result.IsValid()}")

    if result.GetError().Fail():
        print(f"DEBUG: Error: {result.GetError()}")
        return []

    ptr = result.GetValueAsUnsigned()
    print(f"DEBUG: ptr = 0x{ptr:x}")
```

### Metrics Tell the Story

The performance summary reveals issues:
```
Expressions: 1      # Only 1 expression ran - early failure
Memory reads: 0     # No memory reads - expression returned 0
```

vs working:
```
Expressions: 33     # Multiple expressions succeeded
Memory reads: 1,575 # Lots of memory reads - processing data
```

## Runtime Function Availability

### objc_copyImageNames / objc_copyClassNamesForImage

These runtime functions return arrays that must be `free()`d:

```python
# Get array pointer
ptr = evaluate_expression(frame, "objc_copyImageNames(&count)")

# ... use the data ...

# MUST free the array
evaluate_expression(frame, f"(void)free((void *)0x{ptr:x})")
```

### Path Differences: LLDB vs Runtime

**Problem:** LLDB's module paths differ from what the ObjC runtime uses, especially with dyld shared cache.

- LLDB module path: May be empty or cache path
- Runtime path: `/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation`

**Solution:** Use `objc_copyImageNames()` to get paths the runtime recognizes, not LLDB's `target.module_iter()`.

## Quick Debugging Checklist

1. **Changes not taking effect?** → Use `oreload` or `--no-lldbinit`
2. **Expression returning 0?** → Check if runtime is initialized (breakpoint timing)
3. **Expression timing out?** → Split into multiple simple expressions
4. **Ambiguous symbol errors?** → Use unique variable name prefixes
5. **Memory reads showing 0?** → Expression failed silently - add debug prints
6. **Works in LLDB prompt but not Python?** → Check expression string escaping
