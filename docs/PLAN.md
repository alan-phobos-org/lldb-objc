# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.2 (Stable)

The project has a solid foundation with 10+ commands covering the core use cases:

| Status | Command | Description |
|--------|---------|-------------|
| Done | `obrk` | Set breakpoints on ObjC methods |
| Done | `osel` | Find methods in a class |
| Done | `ocls` | Find classes by pattern (optimized + hierarchy + ivars/properties) |
| Done | `ocall` | Call ObjC methods from CLI |
| Done | `owatch` | Auto-logging breakpoints |
| Done | `oprotos` | Protocol conformance finder |
| Done | `opool` | Find instances in autorelease pools |
| Done | `oinstance` | Detailed object inspection |
| Done | `oexplain` | LLM-powered disassembly explanation |
| Done | `odecompile` | LLM-powered decompilation |

## Next Milestone: v1.3

### Priority 1: Cross-Class Method Search

Extend `osel` to search across multiple classes:

```bash
osel CS* symbol*
# -[CSSymbolOwner symbolWithName:]
# -[CSSymbolicator symbolOwnerForName:]
# Total: 4 methods in 3 classes
```

**Why**: Currently requires running osel on each class manually.

### Priority 2: Better Error Messages

Add "did you mean" suggestions for common errors:

```bash
(lldb) ocall [NSDate distancePast]
error: Invalid receiver 'NSDate'. For instance methods, use $variable or hex address.
Did you mean: +[NSDate distantPast]?
```

**Why**: Common typos and confusion between class/instance methods.

### Priority 3: Shared Cache Class Scanning

Support classes in the dyld shared cache that aren't directly loaded:

```bash
ocls --shared-cache NS*
```

**Why**: Many system classes are in shared cache but not enumerated by `objc_getClassList`.

## Backlog

### High Value

| Feature | Description | Complexity |
|---------|-------------|------------|
| `oheap` | Find live instances on heap via malloc introspection | High |
| `ocat` | Category method inspector / collision detector | Medium |
| Fuzzy matching | Suggest corrections for typos | Low |

### Medium Value

| Feature | Description | Complexity |
|---------|-------------|------------|
| `oswizzle` | Runtime method swizzling | Medium |
| `oblock` | Block inspector (signature, invoke) | Medium |
| Test coverage | Add more edge case tests | Low |
| CI/CD | GitHub Actions for unit tests | Low |

### Low Priority

| Feature | Description | Complexity |
|---------|-------------|------------|
| Cross-platform | Linux support for unit tests | Low |
| `ograph` | Class hierarchy visualization | Medium |
| `omemory` | Memory layout inspector | High |

## Known Issues

### Bitfield Position Tracking
The `--ivars` output shows bitfields with bit width but not position within the byte. The runtime's `ivar_getOffset()` only returns byte offset, not bit position.

### Integration Test Stability
Some tests are timing-sensitive and may fail intermittently:
- `test_hierarchy.py` NSMutable* timeout on slow machines
- Shared LLDB session can accumulate state

## Performance Notes

Batch size **35** is optimal. Key optimizations:
- Bulk `ReadMemory()` instead of per-item expressions
- Objective-C blocks for compound expressions
- Per-process caching (<0.01s on subsequent queries)

| Scenario | Time |
|----------|------|
| First run (~10K classes) | ~12s |
| Cached run | <0.01s |

## Design Decisions Log

See [DESIGN.md](DESIGN.md) for architecture details.

| Decision | Rationale |
|----------|-----------|
| Use SBAddress not raw ints | Proper ASLR handling on iOS |
| Batch size 35 | Empirically tested optimal |
| Separate core/utils | Enable pure Python unit testing |
| llm CLI as default | More flexible than Claude-only |

## Contributing

1. Check this roadmap for unclaimed work
2. Discuss approach in an issue first for larger features
3. Follow the development workflow in [AGENTS.md](../AGENTS.md)
4. Run `./build.sh check` before submitting PRs
