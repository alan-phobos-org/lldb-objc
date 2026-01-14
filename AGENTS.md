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
| [docs/PITFALLS.md](docs/PITFALLS.md) | Technical gotchas | Debugging failures |
| [docs/TESTING.md](docs/TESTING.md) | Test guide | Writing tests |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md) | Optimization | Performance work |
| [CHANGELOG.md](CHANGELOG.md) | Release notes | Preparing releases |

## Quick Reference

### Build Commands

| Command | Purpose |
|---------|---------|
| `./build.sh check` | **Pre-commit** (lint + test) |
| `./build.sh test` | Unit tests only (pytest) |
| `./build.sh test-quick` | Quick integration tests |
| `./build.sh test-all` | Unit + integration |
| `./build.sh lint` | Format and lint |

### Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `obrk` | Set breakpoints | `obrk -[Class sel:]` |
| `osel` | Find methods | `osel NSString *init*` |
| `ocls` | Find classes | `ocls IDS* --ivars` |
| `ocall` | Call methods | `ocall [$0 description]` |
| `owatch` | Auto-log breakpoints | `owatch --minimal -[NSString init]` |
| `oprotos` | Protocol conformance | `oprotos --list *Delegate` |
| `opool` | Find in autorelease pools | `opool NSDate` |
| `oinstance` | Inspect object | `oinstance $0` |
| `oexplain` | Explain disassembly | `oexplain $pc` |
| `odecompile` | Decompile function | `odecompile $pc` |
| `osbx` | Scan sandbox writable paths | `osbx --quick` |
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
scripts/              # Command modules
  __init__.py         # Loader with reload support
  objc_*.py           # Individual commands
  objc_core.py        # Pure Python (unit testable)
  objc_utils.py       # LLDB-dependent utilities
  objc_llm.py         # LLM integration
build.sh              # Build, test, release
install.py            # Installer
tests/
  unit/               # Pure Python tests (pytest)
  integration/        # LLDB integration tests
```

---

## Testing [READ IF: implementing features, fixing bugs]

### Test Commands

| Command | Purpose | Speed |
|---------|---------|-------|
| `./build.sh test` | Unit tests (pytest) | <0.1s |
| `./build.sh test-quick` | Quick integration | ~30s |
| `./build.sh test-int` | Full integration | ~2-3min |
| `./build.sh test-all` | Unit + integration | ~3min |

### Test Workflow
- **Before committing**: `pytest` + `./build.sh test-quick`
- **After refactoring**: Full integration suite
- **After output changes**: Manually verify in actual LLDB session

### Code Organization for Testability

| Module | Contains | Testing |
|--------|----------|---------|
| `objc_core.py` | Pure Python (parsing, formatting) | Unit tests |
| `objc_utils.py` | LLDB-dependent operations | Integration tests |
| Command files | Orchestration | Integration tests |

---

## Adding Commands [READ IF: implementing new commands]

1. Create `scripts/objc_<name>.py` with `__lldb_init_module()` printing one-line load message
2. Add module name to `COMMAND_MODULES` list in `scripts/__init__.py`
3. Add integration tests in `tests/test_<name>.py`
4. Extract pure functions to `objc_core.py` and add unit tests
5. Update command tables in this file and README.md
6. Test with `oreload` in LLDB session
7. Run `./build.sh check`

---

## Release Process [READ IF: user explicitly requests release]

```bash
# 1. Run all checks
./build.sh prepare-release

# 2. Update CHANGELOG.md (add: ## [X.Y.Z] - YYYY-MM-DD)

# 3. Review docs for completed TODOs

# 4. Create release
./build.sh release X.Y.Z

# 5. Push
git push origin main vX.Y.Z
```

---

## Key Technical Details [READ IF: debugging or extending]

### Resolution Chain (obrk)

```
NSClassFromString() → Class → NSSelectorFromString() → SEL
→ [+methods] object_getClass() → MetaClass
→ class_getMethodImplementation() → IMP
→ ResolveLoadAddress() → SBAddress → BreakpointCreateBySBAddress()
```

Uses `SBAddress` to handle ASLR on all platforms.

### Performance

| Operation | Speed | Strategy |
|-----------|-------|----------|
| `EvaluateExpression()` | 10-50ms | Minimize |
| `ReadMemory()` | <1ms | Maximize |
| Batch class names | - | 35 per call |
| Cached vs uncached | 0.01s vs 12s | Per-process cache |

### UI Convention

- Primary: normal text
- Secondary: dim gray `\033[90m...\033[0m`

For detailed pitfalls, see [docs/PITFALLS.md](docs/PITFALLS.md).

---

## Installation

```bash
./install.py              # Install to ~/.lldb-objc
./install.py --uninstall  # Remove installation
./install.py --status     # Check status
```
