# HelloWorld-Optimised Example

A heavily optimized and stripped Objective-C binary for testing LLDB command robustness against real-world stripped binaries.

## Purpose

This binary tests how well the LLDB commands work when:
- Debug symbols are stripped (`strip -x`)
- Aggressive compiler optimizations are applied (`-O3`, `-flto`)
- Dead code is eliminated (`-dead_strip`)
- Visibility is restricted (`-fvisibility=hidden`)

This simulates debugging production/release binaries where symbol information is minimal.

## Build Flags

| Flag | Effect |
|------|--------|
| `-O3` | Aggressive optimization (inlining, vectorization, etc.) |
| `-DNDEBUG` | Disable debug assertions |
| `-flto` | Link-time optimization (whole-program analysis) |
| `-fno-exceptions` | Disable C++ exceptions |
| `-fvisibility=hidden` | Hide symbols by default |
| `-dead_strip` | Remove unused code |
| `strip -x` | Remove local symbols from binary |

## Building

```bash
make          # Build optimized + stripped binary
make debug    # Build with debug symbols (for comparison)
make info     # Show binary info (symbols, size, etc.)
make clean    # Remove build artifacts
```

## Testing with LLDB

```bash
cd ../../tests
./test_bootstrap_optimised.py
```

## What to Test

Commands should still work because Objective-C runtime metadata survives stripping:

```lldb
# These rely on runtime introspection, not debug symbols
ocls Greeter --ivars --properties
osel Greeter *
obrk -[Greeter sayHello:]
oinstance (id)[[Greeter alloc] init]

# These may have degraded output without symbols
oexplain $pc          # Less symbol names in disassembly
odecompile $pc        # Function boundaries may be unclear
```

## Expected Differences from Debug Build

1. **No source-level debugging** - Can't step by line
2. **Inlined functions** - Some methods may be inlined into callers
3. **Missing local symbols** - Variables names not available
4. **Optimized code paths** - Assembly may look different from source

However, Objective-C runtime metadata (class names, method selectors, ivars) should remain intact because the runtime needs them.
