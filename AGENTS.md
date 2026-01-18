# LLDB Objective-C Tools

LLDB commands for Objective-C runtime introspection, including private classes/methods.

## Vision

Commands that feel like native debugger features, not bolted-on scripts. Output should be scannable at a glance - primary info prominent, secondary details muted. Fast enough to run speculatively. Error messages should suggest what the user probably meant. Handle edge cases gracefully (nil objects, swizzled methods, stripped binaries) rather than crashing or producing confusing output.

## Documentation

| Document | Purpose | Read When |
|----------|---------|-----------|
| [AGENTS.md](AGENTS.md) | Development workflow, commands | Always |
| [docs/PLAN.md](docs/PLAN.md) | Roadmap, backlog | Planning work |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture, patterns | Major refactoring |
| [docs/SANDBOX_DESIGN.md](docs/SANDBOX_DESIGN.md) | Sandbox scanner design | Working on osbx |
| [docs/SANDBOX_SUMMARY.md](docs/SANDBOX_SUMMARY.md) | Sandbox testing summary | Quick reference for sandbox work |
| [docs/DEBUGGING.md](docs/DEBUGGING.md) | LLDB Python script debugging | Debugging script failures |
| [docs/PITFALLS.md](docs/PITFALLS.md) | Technical gotchas | Debugging failures |
| [docs/TESTING.md](docs/TESTING.md) | Test guide | Writing tests |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md) | Optimization | Performance work |
| [docs/OCLS_OPTIMIZATION.md](docs/OCLS_OPTIMIZATION.md) | ocls speedup techniques | Optimizing class enumeration |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Adding commands, releasing | New features, releases |
| [CHANGELOG.md](CHANGELOG.md) | Release notes | Preparing releases |

## Development Environment

**CRITICAL**: All development AND testing MUST be done inside the `.venv` virtual environment. If you see pexpect errors you aren't in the `.venv`!

```bash
source .venv/bin/activate  # Always activate first
which python               # Should show .venv/bin/python
```

The venv includes all dependencies (pytest, pexpect, etc.). If you're not in the venv, commands and imports will fail.

### Sudo Configuration for System Process Testing

Smoke tests and some integration tests attach to system processes (e.g., `apsd`) which requires sudo. See `.sudo/` directory for setup scripts (gitignored).

## Quick Reference

### Build Commands

| Command | Purpose |
|---------|---------|
| `./build.sh check` | **Pre-commit** (lint + all tests) |
| `./build.sh test-unit` | Unit tests only (pytest) |
| `./build.sh test-smoke` | Smoke tests against system process (depends on test-unit) |
| `./build.sh test-integration` | All integration tests |
| `./build.sh test-integration <cmd>` | **Fast re-test**: Single integration suite (e.g., `ocls`) |
| `./build.sh lint` | Format and lint |

### Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `obrk` | Set breakpoints | `obrk -[Class sel:]` |
| `osel` | Find methods | `osel NSString *init*` |
| `ocls` | Find classes | `ocls CS* --ivars` |
| `ocall` | Call methods | `ocall [$0 description]` |
| `owatch` | Auto-log breakpoints | `owatch --minimal -[NSString init]` |
| `opool` | Find in autorelease pools | `opool NSDate` |
| `oinstance` | Inspect object | `oinstance $0` |
| `oinstances` | Find class instances in memory | `oinstances NSString` |
| `okeychain` | Query keychain items | `okeychain list --keychain=/path.db` |
| `osbx` | Scan sandbox writable paths | `osbx --thorough` |
| `oreload` | Reload commands | `oreload` |

## Workflows

| Trigger | Action |
|---------|--------|
| Before any commit | `./build.sh check` |
| "what's next", "status" | `./build.sh status` → read `docs/PLAN.md` → summarize (10-15 lines) |
| "prepare release" | `./build.sh prepare-release` → update CHANGELOG.md → `./build.sh release X.Y.Z` → push |
| Development reload | `oreload` in LLDB session |
| Install locally | `./install.py` |

---

## CRITICAL: Git Commit Messages

**NEVER include any AI/agent identifiers in commit messages.** This applies to ALL commits, especially releases.

Forbidden in commit messages:
- "Claude", "Anthropic", "AI", "LLM", "Codex", "GPT", "OpenAI", "Gemini", "Copilot"
- "generated", "automated", "assisted by", "with help from"
- Co-Authored-By headers mentioning AI
- "Generated with [tool name]" footers
- Any emoji

Write commit messages as a human developer would:
- Focus on WHAT changed and WHY
- Use conventional commit format (feat:, fix:, refactor:, etc.)
- Keep messages concise and professional

**This rule is absolute and applies to every commit including releases and version bumps.**

## Project Structure

```
scripts/              # LLDB command modules
  __init__.py         # Loader with reload support
  objc_*.py           # Individual commands
  objc_core.py        # Pure Python (unit testable)
  objc_utils.py       # LLDB-dependent utilities
tools/
  osbx-standalone/    # Standalone sandbox scanner binary
build.sh              # Build, test, release
install.py            # Installer
tests/
  unit/               # Pure Python tests (pytest)
  test_bootstrap*.py  # Bootstrap scripts (auto-load commands)
  bootstrap_common.py # Shared bootstrap utilities
examples/             # Example projects for testing
docs/                 # Design documents and guides
```

### Key Files

- [scripts/objc_breakpoint.py](scripts/objc_breakpoint.py) - The `obrk` command implementation
- [scripts/objc_dump.py](scripts/objc_dump.py) - The `odump` command for dumping NSData/memory to files
- [scripts/objc_entitlements.py](scripts/objc_entitlements.py) - The `oentitlements` command for extracting process entitlements
- [scripts/objc_keychain.py](scripts/objc_keychain.py) - The `okeychain` command for querying keychain items
- [scripts/objc_pool.py](scripts/objc_pool.py) - The `opool` command for scanning autorelease pools
- [scripts/objc_instances.py](scripts/objc_instances.py) - The `oinstances` command for finding class instances in memory
- [scripts/objc_utils.py](scripts/objc_utils.py) - Utility functions for method resolution
- [scripts/objc_core.py](scripts/objc_core.py) - Core parsing and formatting functions
- [tests/test_obrk.py](tests/test_obrk.py) - Comprehensive test suite for breakpoint functionality
- [tests/test_odump.py](tests/test_odump.py) - Test suite for odump command
- [tests/test_oentitlements.py](tests/test_oentitlements.py) - Test suite for oentitlements command
- [tests/test_okeychain.py](tests/test_okeychain.py) - Test suite for okeychain command
- [tests/test_opool.py](tests/test_opool.py) - Test suite for opool command
- [tests/test_oinstances.py](tests/test_oinstances.py) - Test suite for oinstances command

### Implementation Notes

**okeychain**: Supports iOS and macOS. Auto-detects process-specific keychains on macOS (e.g., `/Library/Keychains/apsd.keychain`). Use `--keychain=<path>` for iOS remote debugging or custom keychain files. Uses `SecKeychainOpen` + `kSecMatchSearchList` to mirror how binaries access their own keychains.

For detailed implementation patterns (LLDB expression evaluation, data extraction, etc.), see:
- [docs/PITFALLS.md](docs/PITFALLS.md) - Common gotchas and workarounds
- [docs/DEBUGGING.md](docs/DEBUGGING.md) - Debugging LLDB scripts
- [docs/DESIGN.md](docs/DESIGN.md) - Architecture and design patterns

---

## Testing [READ IF: implementing features, fixing bugs]

Use `./build.sh test-unit` to verify changes are robust.

### Test Commands

| Command | Purpose | Speed |
|---------|---------|-------|
| `./build.sh test-unit` | Unit tests (pytest) | <0.1s |
| `./build.sh test-smoke` | Quick smoke tests vs system process | ~5-10s |
| `./build.sh test-integration` | All integration tests | ~2-3min |
| `./build.sh test-integration <cmd>` | Single integration suite | ~5-10s |
| `./build.sh check` | Full pre-commit (unit + all integration) | ~3min |

**Fast re-testing workflow**: After fixing a specific command (e.g., `ocls`), use `./build.sh test-integration ocls` to run unit tests + just that command's integration suite.

Available integration test commands: `obrk`, `ocall`, `ocls`, `odump`, `oentitlements`, `oinstance`, `oinstances`, `okeychain`, `opool`, `osbx`, `osel`, `owatch`, `hierarchy`, `ivars_props`, `timing`

Individual test suites can also be run directly:

```bash
.venv/bin/python3 tests/test_obrk.py
```

Tests use shared LLDB sessions for performance. The HelloWorld examples in [examples/](examples/) are used as test targets.

### Test Workflow
- **Before committing**: `./build.sh check`
- **Fast re-test after fix**: `./build.sh test-integration <command>`
- **After refactoring**: Full integration suite
- **After output changes**: Manually verify in actual LLDB session

### Code Organization for Testability

| Module | Contains | Testing |
|--------|----------|---------|
| `objc_core.py` | Pure Python (parsing, formatting) | Unit tests |
| `objc_utils.py` | LLDB-dependent operations | Integration tests |
| Command files | Orchestration | Integration tests |

## Adding Commands [READ IF: implementing new commands]

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#adding-commands).

## Release Process [READ IF: user explicitly requests release]

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#release-process).
