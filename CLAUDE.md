# LLDB Objective-C Tools

LLDB commands for Objective-C runtime introspection, including private classes/methods.

## Commands

| Command | Purpose | Key Flags |
|---------|---------|-----------|
| `obrk` | Set breakpoints | `obrk -[Class sel:]` or `obrk +[Class method:]` |
| `osel` | Find methods | `--instance`, `--class`, `--reload`, `--verbose` |
| `ocls` | Find classes | `--ivars`, `--properties`, `--dylib`, `--batch-size=N` |
| `ocall` | Call methods | Supports `@"string"`, `@42`, expressions |
| `owatch` | Auto-log breakpoints | `--minimal`, `--stack` |
| `oprotos` | Protocol conformance | `--list [pattern]` |
| `opool` | Find instances in pools | `--verbose` |
| `oinstance` | Inspect object | `oinstance <addr\|$var\|expr>` |

### Quick Examples
```bash
ocls IDS*                           # Classes starting with IDS
ocls NSString --ivars --properties  # Show class details
ocls --dylib CoreFoundation CF*     # Classes from specific dylib
osel IDSService send*               # Methods matching pattern
osel NSString --instance *init*     # Instance methods only
obrk -[IDSService sendMessage:]     # Set breakpoint
owatch --minimal -[NSString init]   # Watch with timestamps
oprotos --list *Delegate            # List delegate protocols
opool NSDate                        # Find NSDate in autorelease pools
opool --verbose NSString            # Show pool contents while searching
oinstance (id)[NSDate date]         # Inspect specific object
oinstance 0x12345678                # Inspect by address
oinstance $0                        # Inspect LLDB variable
```

## Installation
```bash
./install.py              # Install to ~/.lldbinit
./install.py --uninstall  # Remove
```

## Project Structure
```
objc_breakpoint.py  # obrk       objc_watch.py    # owatch
objc_sel.py         # osel       objc_protos.py   # oprotos
objc_cls.py         # ocls       objc_pool.py     # opool
objc_call.py        # ocall      objc_instance.py # oinstance
objc_utils.py       # shared     install.py       # installer
tests/              # test suite
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

### Output Formatting
- Avoid duplicate or redundant information in formatted output
- Each piece of information should appear exactly once in the most appropriate location
- When multiple sources provide the same data (e.g., type info from both value description and type decoding), choose the most user-friendly presentation

### Common Pitfalls
- **String handling**: Use `s[1:-1]` not `strip('"')` for LLDB `GetSummary()` strings
- **F-strings with blocks**: Use `^{{` and `}}` for Objective-C blocks in f-strings
- **API validation**: Before using unfamiliar API methods (especially in external libraries like LLDB), verify they exist:
  - Check existing code for similar usage patterns
  - Look for the method in API objects using `dir()` in similar contexts
  - Test the API call in isolation before integrating it
  - If uncertain, acknowledge the uncertainty and propose verification steps
  - Example: `SBExpressionOptions.SetSuppressAllOutput()` doesn't exist—should have checked `dir(lldb.SBExpressionOptions())` or looked for similar usage in codebase

### Testing & Verification Protocol
- **Always run tests**: After making changes, run the test suite before claiming success
- **Verify in actual environment**: Tests passing is necessary but not sufficient—manually verify changes work in the actual runtime environment (e.g., test LLDB commands in an actual LLDB session, not just via test framework)
- **Verify output formatting**: After changes that affect user-facing output, manually inspect the formatted results to ensure:
  - No duplicate or redundant information
  - Consistent alignment and spacing
  - Proper use of color codes for primary vs secondary information
  - Appropriate truncation of long values
- **Validate test quality**: When tests pass but something seems wrong, investigate whether tests are actually catching the error types they should
- **Test the test framework**: Test infrastructure itself needs validation—ensure it catches exceptions, tracebacks, and error conditions properly
- **Don't trust tests blindly**: If manual testing reveals a bug that tests missed, improve the test framework to catch that class of errors in the future

Example: If implementing a feature that uses an API method, verify the method exists by testing in isolation before assuming tests validate everything.

### Root Cause Analysis
- **Investigate unexpected outcomes**: When something unexpected happens (tests pass but code fails, errors aren't caught, etc.), don't just fix the immediate problem—investigate why it happened
- **Improve infrastructure**: Treat test failures and gaps as opportunities to improve the development infrastructure itself
- **Example from this project**: When `oinstance` failed at runtime despite tests passing, the correct response was:
  1. Fix the immediate bug (remove `SetSuppressAllOutput`)
  2. Investigate why tests didn't catch it (test framework wasn't detecting Python tracebacks)
  3. Improve test framework to catch this class of errors (add traceback detection to `test_helpers.py`)
- **Ask "why" multiple times**: Don't stop at surface-level fixes; understand and address underlying causes

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
