# LLDB Objective-C Tools

LLDB commands for Objective-C runtime introspection, including private classes/methods.

## Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `obrk` | Set breakpoints | `obrk -[Class sel:]` or `obrk +[Class method:]` |
| `osel` | Find methods | `osel ClassName [pattern]` with `--instance`/`--class` |
| `ocls` | Find classes | `ocls [pattern]` with `--ivars`/`--properties` |
| `ocall` | Call methods | `ocall +[NSDate date]` or `ocall -[$var sel]` |
| `owatch` | Auto-log breakpoints | `owatch -[Class sel]` with `--minimal`/`--stack` |
| `oprotos` | Protocol conformance | `oprotos NSCoding` or `oprotos --list` |

### Quick Examples
```bash
ocls IDS*                           # Classes starting with IDS
ocls NSString --ivars --properties  # Show class details
osel IDSService send*               # Methods matching pattern
obrk -[IDSService sendMessage:]     # Set breakpoint
owatch --minimal -[NSString init]   # Watch with timestamps
oprotos --list *Delegate            # List delegate protocols
```

## Installation
```bash
./install.py              # Install to ~/.lldbinit
./install.py --uninstall  # Remove
```

## Project Structure
```
objc_breakpoint.py  # obrk     objc_watch.py   # owatch
objc_sel.py         # osel     objc_protos.py  # oprotos
objc_cls.py         # ocls     objc_utils.py   # shared utilities
objc_call.py        # ocall    install.py      # installer
tests/              # test suite (run_all_tests.py)
```

## Performance Strategy
- `frame.EvaluateExpression()` is slow (10-50ms) → minimize
- `process.ReadMemory()` is fast (<1ms) → maximize
- Batch using Objective-C blocks, optimal batch size: **35**
- Cache per-process: first run ~12s, cached <0.01s

## Development Guidelines

### Adding Commands
1. Create `objc_<name>.py` with `__lldb_init_module()`
2. Add to `install.py`
3. Add tests in `tests/test_<name>.py`
4. Update README.md

### UI Convention
Primary info in normal text; secondary (types, hierarchy) in dim gray: `\033[90m...\033[0m`

### Common Pitfalls
- **String handling**: Use `s[1:-1]` not `strip('"')` for LLDB `GetSummary()` strings
- **F-strings with blocks**: Use `^{{` and `}}` for Objective-C blocks in f-strings

## Tests
```bash
./tests/run_all_tests.py          # All tests
./tests/run_all_tests.py --quick  # Quick subset
```

## Resolution Chain (obrk)
```
NSClassFromString() → Class → NSSelectorFromString() → SEL
→ object_getClass() (for +methods) → class_getMethodImplementation() → IMP
→ BreakpointCreateByAddress()
```

## Future Work
See [docs/PLAN.md](docs/PLAN.md) for roadmap including wildcard `osel`, `oheap`, `ocat`.
