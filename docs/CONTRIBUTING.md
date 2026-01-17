# Contributing to lldb-objc

## Adding Commands

1. Create `scripts/objc_<name>.py` with `__lldb_init_module()` printing one-line load message
2. Add module name to `COMMAND_MODULES` list in `scripts/__init__.py`
3. Add integration tests in `tests/test_<name>.py`
4. Extract pure functions to `objc_core.py` and add unit tests
5. Update command tables in AGENTS.md and README.md
6. Test with `oreload` in LLDB session
7. Run `./build.sh check`

## Release Process

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
