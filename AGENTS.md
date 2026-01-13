# LLDB Objective-C Tools

LLDB commands for Objective-C runtime introspection, including private classes/methods.

## Development Workflow

Before committing, always run:
```bash
./build.sh check
```

This runs:
1. Linter (ruff or flake8)
2. Unit tests (pytest)
3. Quick integration tests

## Release Process

To create a release:

```bash
# Step 1: Run all automated checks and tests
./build.sh prepare-release

# Step 2: Update CHANGELOG.md with release notes (requires human/LLM)
# Add a new section: ## [X.Y.Z] - YYYY-MM-DD

# Step 3: Review docs (AGENTS.md, README.md) for completed work
# Remove or mark done any TODO items, planned features now implemented, etc.

# Step 4: Create the release commit and tag
./build.sh release X.Y.Z

# Step 5: Push to remote
git push origin main vX.Y.Z
```

## Build Commands

```bash
./build.sh version          # Show current version (from git)
./build.sh test             # Unit tests only (pytest)
./build.sh test-int         # Full integration tests
./build.sh test-quick       # Quick integration tests
./build.sh test-all         # Unit + integration tests
./build.sh lint             # Format and lint
./build.sh check            # Full pre-commit check
./build.sh dist             # Create release zip package
./build.sh deploy-local     # Build dist and install locally
./build.sh prepare-release  # Run all release checks and show changes
./build.sh release X.Y.Z    # Create release commit and tag
./build.sh clean            # Remove build artifacts
```

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
| `oexplain` | Explain disassembly via LLM | `--annotate`, `--claude` (uses llm by default) |
| `odecompile` | Decompile via LLM | `--claude` (uses llm by default) |
| `oreload` | Reload all commands | No flags (for development) |

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
oexplain $pc                        # Explain current function (uses llm)
oexplain 0x12345678                 # Explain function at address
oexplain -a $pc                     # Annotate disassembly line-by-line
oexplain --claude $pc               # Use Claude CLI instead of llm
odecompile $pc                      # Decompile current function (uses llm)
odecompile 0x12345678               # Decompile function at address
odecompile --claude $pc             # Use Claude CLI instead of llm
```

## Installation
```bash
./install.py              # Install to ~/.lldb-objc and update ~/.lldbinit
./install.py --uninstall  # Remove ~/.lldb-objc and clean ~/.lldbinit
./install.py --status     # Check installation status
```

Scripts are copied to `~/.lldb-objc/scripts/` for a stable installation path. The installer updates `~/.lldbinit` to load from this permanent location.

For development, use `oreload` within LLDB to reload commands after making changes to the source.

## Project Structure
```
scripts/            # Command modules (directory import)
  __init__.py       # Loader with reload support
  objc_breakpoint.py  # obrk
  objc_sel.py         # osel
  objc_cls.py         # ocls
  objc_call.py        # ocall
  objc_watch.py       # owatch
  objc_protos.py      # oprotos
  objc_pool.py        # opool
  objc_instance.py    # oinstance
  objc_explain.py     # oexplain
  objc_decompile.py   # odecompile
  objc_llm.py         # Shared LLM utilities (symbol lookup, registers, CLI wrappers)
  objc_utils.py       # LLDB-dependent utilities
  objc_core.py        # Pure Python utilities (unit testable)
  version.py          # Git-based version info
build.sh            # Build, test, and release script
install.py          # Installer
CHANGELOG.md        # Release notes
tests/              # Test suite
  unit/             # Pure Python unit tests (pytest)
  integration/      # LLDB integration tests (current tests)
```

## Performance Strategy
- `frame.EvaluateExpression()` is slow (10-50ms) → minimize
- `process.ReadMemory()` is fast (<1ms) → maximize
- Batch using Objective-C blocks, optimal batch size: **35**
- Cache per-process: first run ~12s, cached <0.01s

## Development Guidelines

### Adding Commands
1. Create `scripts/objc_<name>.py` with `__lldb_init_module()` printing one-line load message
2. Add module name to `COMMAND_MODULES` list in `scripts/__init__.py`
3. Add integration tests in `tests/test_<name>.py`
4. Extract pure functions to `objc_core.py` and add unit tests in `tests/unit/`
5. Update README.md and AGENTS.md command tables
6. Test with `oreload` in LLDB session to verify reload works
7. Run `./build.sh check` before committing

### Code Organization for Testability
- **objc_core.py**: Pure Python logic (parsing, formatting, pattern matching) - fully unit testable
- **objc_utils.py**: LLDB-dependent utilities (`frame.EvaluateExpression()`, runtime introspection)
- **Command files**: Thin entry points that orchestrate core logic and LLDB APIs
- Import from `objc_core` for pure functions, `objc_utils` for LLDB operations

### UI Convention
Primary info in normal text; secondary (types, hierarchy) in dim gray: `\033[90m...\033[0m`

### Output Formatting
- Avoid duplicate or redundant information in formatted output
- Each piece of information should appear exactly once in the most appropriate location
- When multiple sources provide the same data (e.g., type info from both value description and type decoding), choose the most user-friendly presentation

### Common Pitfalls
- **String handling**: Use `s[1:-1]` not `strip('"')` for LLDB `GetSummary()` strings
- **F-strings with blocks**: Use `^{{` and `}}` for Objective-C blocks in f-strings
- **ASLR/address handling**: Always use `SBAddress` for breakpoints, never raw ints. Load addresses from runtime (e.g., `class_getMethodImplementation()`) are already ASLR-adjusted. Use `target.ResolveLoadAddress(addr)` → `SBAddress`, then `BreakpointCreateBySBAddress(sbaddr)` not `BreakpointCreateByAddress(int)`. iOS has aggressive ASLR—bugs may only manifest there.
- **API validation**: Verify LLDB methods exist via `lldb -b -o "script help(lldb.SBTarget.MethodName)"`. Check signatures with `help()`, inspect available methods with `dir()`. Test in isolation before integrating.
- **Function signature changes**: When changing return types (e.g., `int` → `SBAddress`), grep for all callers and update them atomically in one change.
- **Import locations**: Pure Python utilities belong in `objc_core.py` (e.g., `unquote_string`, `extract_category_from_symbol`). Import from the correct module—don't assume re-exports exist.
- **Caching with filter flags**: When caching data, ensure partial queries (e.g., `--instance` only) don't corrupt the cache for full queries. Either skip caching, or always fetch complete data and filter at display time.
- **Memory allocation cleanup**: When allocating memory in the target process via `malloc()`, ensure cleanup happens even on exceptions. Consider try/finally patterns for `EvaluateExpression("free(...)")`.

### Testing & Verification Protocol

#### Setup
```bash
# Use Python 3.11 (Homebrew Python 3.14 is externally-managed)
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m pip install -r requirements-dev.txt
```

#### Test Layers
1. **Unit Tests** (pytest) - Pure Python logic, no LLDB required
   ```bash
   pytest                    # All unit tests
   pytest -v                 # Verbose
   pytest -m parsing         # Only parsing tests
   pytest --cov              # With coverage
   ```
   - Fast (<0.1s total)
   - Test parsing, formatting, pattern matching
   - Cross-platform (can run on Linux)

2. **Integration Tests** - Full LLDB commands with runtime (use Python 3.11)
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 ./tests/run_all_tests.py          # All
   /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 ./tests/run_all_tests.py --quick  # Quick subset
   ```
   - Slower (~2-3 min for full suite)
   - macOS-only (requires LLDB + Objective-C runtime)

#### Testing Workflow
- **Before committing**: Run `pytest` (fast) + `./tests/run_all_tests.py --quick`
- **After refactoring**: Run full integration suite
- **Always run tests**: After making changes, run test suite before claiming success
- **Platform testing**: macOS and iOS differ in ASLR, framework loading, and runtime behavior. Bugs may only manifest on iOS. Consider platform-specific edge cases.
- **Verify in actual environment**: Tests passing is necessary but not sufficient—manually verify changes work in the actual runtime environment (e.g., test LLDB commands in an actual LLDB session, not just via test framework)
- **Bootstrap test**: After significant refactoring, run `./tests/test_bootstrap.py` (interactive, requires timeout) to verify LLDB integration works
- **Verify output formatting**: After changes that affect user-facing output, manually inspect the formatted results to ensure:
  - No duplicate or redundant information
  - Consistent alignment and spacing
  - Proper use of color codes for primary vs secondary information
  - Appropriate truncation of long values
- **Validate test quality**: When tests pass but something seems wrong, investigate whether tests are actually catching the error types they should
- **Test the test framework**: Test infrastructure itself needs validation—ensure it catches exceptions, tracebacks, and error conditions properly
- **Don't trust tests blindly**: If manual testing reveals a bug that tests missed, improve the test framework to catch that class of errors in the future

### Root Cause Analysis
- **Investigate unexpected outcomes**: When something unexpected happens (tests pass but code fails, errors aren't caught, etc.), don't just fix the immediate problem—investigate why it happened
- **Improve infrastructure**: Treat test failures and gaps as opportunities to improve the development infrastructure itself
- **Example from this project**: When `oinstance` failed at runtime despite tests passing, the correct response was:
  1. Fix the immediate bug (remove `SetSuppressAllOutput`)
  2. Investigate why tests didn't catch it (test framework wasn't detecting Python tracebacks)
  3. Improve test framework to catch this class of errors (add traceback detection to `test_helpers.py`)
- **Ask "why" multiple times**: Don't stop at surface-level fixes; understand and address underlying causes

## Testing

See [Testing & Verification Protocol](#testing--verification-protocol) above for full details.

**Quick Reference:**
```bash
pip install -r requirements-dev.txt  # Install test dependencies

# Using build.sh (recommended)
./build.sh test        # Unit tests only
./build.sh test-quick  # Quick integration tests
./build.sh test-int    # Full integration tests
./build.sh test-all    # Unit + integration tests
./build.sh check       # Full pre-commit check

# Direct pytest (unit tests)
pytest                           # All unit tests
pytest -v                        # Verbose
pytest tests/unit/test_objc_utils.py::TestParseMethodSignature  # Specific tests
```

## Resolution Chain (obrk)
```
NSClassFromString() → Class → NSSelectorFromString() → SEL
→ object_getClass() (for +methods) → class_getMethodImplementation() → IMP
→ ResolveLoadAddress() → SBAddress → BreakpointCreateBySBAddress()
```
Note: Uses `SBAddress` instead of raw addresses to properly handle ASLR/slide on iOS and other platforms.

## Documentation

- [docs/PLAN.md](docs/PLAN.md) - Roadmap, current stage, and backlog
- [docs/DESIGN.md](docs/DESIGN.md) - Architecture and planned features
- [docs/TESTING.md](docs/TESTING.md) - Testing guide and best practices
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) - Performance optimization
- [docs/UI_CONVENTIONS.md](docs/UI_CONVENTIONS.md) - UI formatting conventions

## Agent Workflows

### What's Next

When asked "what's next" or similar, run this workflow to provide a concise project status summary:

**1. Working Copy Status**
```bash
git status --short
git diff --stat
```
Check for uncommitted changes, staged files, and work in progress.

**2. Remote & CI Status**
```bash
git fetch origin
git log --oneline origin/main..HEAD  # unpushed commits
git log --oneline HEAD..origin/main  # commits to pull
gh run list --limit 5                # recent CI runs
gh release list --limit 3            # recent releases
```
Check if local is ahead/behind remote, CI pass/fail status, and latest release version.

**3. Plan Review**
Read `docs/PLAN.md` and compare against:
- Current release version (from `git describe --tags` or CHANGELOG.md)
- Recently completed work (git log since last tag)
- Next planned milestone or phase
- Backlog items ready to start

**4. Summary Report**
Provide a concise summary covering:
- **Working copy**: clean/dirty, uncommitted changes
- **Remote sync**: ahead/behind, CI status (passing/failing)
- **Current version**: latest release tag
- **Plan status**: current phase completion, next priorities
- **Suggested next step**: one clear recommendation

Keep the report brief (10-15 lines max). Focus on actionable information.
