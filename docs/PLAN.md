# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.3 (Stable)

10 commands covering core debugging use cases: `obrk`, `osel`, `ocls`, `ocall`, `owatch`, `opool`, `oinstance`, `oexplain`, `odecompile`, `osbx`.

Standalone sandbox scanner binary available at `tools/osbx-standalone/`.

## Issue Tracking

Issues, features, and backlog are tracked with [Beads](https://github.com/steveyegge/beads):

```bash
bd ready              # Show next work item
bd list --label v1.4  # v1.4 milestone issues
bd list --label backlog  # Backlog items
bd list --type bug    # Known issues
bd show <id>          # Issue details
```

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
