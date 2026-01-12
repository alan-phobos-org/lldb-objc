# Design Document

High-level architecture, design decisions, and planned features for LLDB Objective-C Tools.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Commands                            │
│  obrk  │  osel  │  ocls  │  ocall  │  owatch  │  oprotos  │ ... │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    Shared Utilities                              │
│  objc_utils.py (LLDB-dependent)  │  objc_core.py (Pure Python)  │
│  objc_llm.py (LLM integration)   │  version.py (Git versioning) │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                      LLDB Python API                             │
│  SBTarget  │  SBProcess  │  SBFrame  │  SBAddress  │  ...       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                   Objective-C Runtime                            │
│  NSClassFromString  │  NSSelectorFromString  │  class_*  │  ... │
└─────────────────────────────────────────────────────────────────┘
```

## Core Design Principles

### 1. Performance First
- `EvaluateExpression()` is slow (10-50ms) → minimize calls
- `ReadMemory()` is fast (<1ms) → use for bulk data
- Batch operations using Objective-C blocks (optimal size: 35)
- Per-process caching for instant repeated queries

### 2. Separation of Concerns
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

### 3. Consistent UI
- Primary info: normal text (class name, method name)
- Secondary info: dim gray `\033[90m` (types, hierarchy, attributes)
- No duplicate information in output
- Progressive detail based on result count

## Command Architecture

### Resolution Chain (obrk)
```
User Input: -[NSString length]
     │
     ▼
NSClassFromString(@"NSString") → Class
     │
     ▼
NSSelectorFromString(@"length") → SEL
     │
     ▼
[for +methods] object_getClass(class) → MetaClass
     │
     ▼
class_getMethodImplementation(class, sel) → IMP (load address)
     │
     ▼
target.ResolveLoadAddress(imp) → SBAddress
     │
     ▼
target.BreakpointCreateBySBAddress(addr) → Breakpoint
```

Note: Uses `SBAddress` throughout to properly handle ASLR on all platforms.

### Class Enumeration (ocls)
```
┌─────────────────────────────────────────┐
│ Fast Path (exact match)                  │
│ NSClassFromString() → single class      │
│ Time: <0.01s                            │
└─────────────────────────────────────────┘
              OR
┌─────────────────────────────────────────┐
│ Full Enumeration (patterns)             │
│ 1. Check cache (instant if hit)         │
│ 2. objc_getClassList() → class count    │
│ 3. Batched class_getName() (batch=35)   │
│ 4. Pattern match + cache results        │
│ Time: ~12s first run, <0.01s cached     │
└─────────────────────────────────────────┘
```

### LLM Integration (oexplain, odecompile)
```
┌─────────────────────────────────────────┐
│ objc_llm.py                             │
├─────────────────────────────────────────┤
│ get_symbol_for_address(addr)            │
│ get_disassembly(addr)                   │
│ get_register_context()                  │
│ run_llm_cli(prompt, ...)                │
│ run_claude_cli(prompt, ...)             │
└─────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────┐
│ External CLI Tools                       │
│ - llm (Simon Willison's tool)           │
│ - claude (Anthropic CLI)                │
└─────────────────────────────────────────┘
```

## Data Flow Patterns

### Memory-Efficient Class Scanning
```python
# Instead of:
for cls in all_classes:
    name = EvaluateExpression(f"class_getName({cls})")  # SLOW

# Do:
batch = all_classes[i:i+35]
names = EvaluateExpression(f"""
    (NSArray *)^{{
        NSMutableArray *r = [NSMutableArray array];
        Class classes[] = {{{batch}}};
        for (int i = 0; i < {len(batch)}; i++)
            [r addObject:@(class_getName(classes[i]))];
        return r;
    }}()
""")  # One call for 35 classes
```

### Caching Strategy
```
Process ID → {
    "classes": {name: class_ptr, ...},
    "timestamp": last_refresh,
    "version": cache_version
}
```
Cache is invalidated on:
- Explicit `--reload` flag
- Process restart (different PID)
- Framework load (via user request)

## Planned Features

### Near-Term

#### Wildcard osel (Cross-Class Search)
```bash
osel IDS* send*
# Searches all classes matching IDS* for methods matching send*
# -[IDSService sendMessage:]
# -[IDSConnection sendAck:]
# Total: 4 methods in 3 classes
```

Design: Reuse existing ocls caching + pattern matching.

#### Enhanced Error Messages
```
error: Invalid receiver 'NSDate'.
Did you mean: +[NSDate distantPast]?
Hint: For instance methods, use $variable, $register, or hex address.
```

Design: Selector fuzzy matching for suggestions.

### Future Features

#### oheap - Heap Instance Scanner
Find live instances on heap via malloc zone introspection.

```bash
oheap NSString                    # All NSString instances on heap
oheap NSString --limit 10         # First 10 instances
oheap NSString --filter length>50 # Filter by expression
```

Design considerations:
- Use `malloc_zone_from_ptr` and `malloc_zone_statistics`
- Iterate heap blocks, check for valid Objective-C objects
- Performance: may need sampling for large heaps

#### ocat - Category Inspector
Detect category methods and potential collisions.

```bash
ocat NSString                     # List all categories on NSString
ocat NSString isEmpty             # Show which category defines isEmpty
ocat --collisions                 # Find method collisions across categories
```

Design: Parse symbol names for category markers `(CategoryName)`.

#### oswizzle - Runtime Method Swizzling
Interactive method swizzling for debugging.

```bash
oswizzle -[NSString length] log   # Log all calls to length
oswizzle -[NSString length] trace # Trace with args/return
oswizzle --restore all            # Restore original implementations
```

Design considerations:
- Use `method_exchangeImplementations`
- Track swizzled methods for restoration
- Handle edge cases (already swizzled, etc.)

#### oblock - Block Inspector
Inspect and decode Objective-C blocks.

```bash
oblock 0x123456789               # Inspect block at address
oblock $0                        # Inspect block in variable
oblock --list                    # List known blocks in scope
```

Design: Parse block literal structure, extract signature and invoke function.

## Testing Architecture

```
┌─────────────────────────────────────────┐
│ Unit Tests (pytest)                     │
│ - Pure Python logic                     │
│ - Fast (<0.1s)                          │
│ - Cross-platform                        │
│ - Run before every commit               │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│ Integration Tests                        │
│ - Full LLDB commands                    │
│ - Shared session (15-25s vs 120s)       │
│ - macOS-only                            │
│ - Pytest-style output                   │
│ - Run before merging                    │
└─────────────────────────────────────────┘
```

See [TESTING.md](TESTING.md) for implementation details.

## Known Limitations

### Bitfield Position Tracking
The `--ivars` output shows bitfields with bit width but not position within the byte. The runtime's `ivar_getOffset()` only returns byte offset, not bit position.

### Platform Differences
- iOS has more aggressive ASLR than macOS
- Some frameworks load differently between platforms
- Simulator vs device may have different class availability

### Performance Tradeoffs
- Full class enumeration takes ~12s on first run
- Caching trades memory for speed
- Batch size 35 is empirically optimal but may vary

## Security Considerations

- Never expose credentials or API keys in code
- Expression evaluation can execute arbitrary code
- LLM prompts should not include sensitive runtime data
- Hooks system should be reviewed for injection risks
