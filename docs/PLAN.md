# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.3 (Stable)

10 commands covering core debugging use cases: `obrk`, `osel`, `ocls`, `ocall`, `owatch`, `opool`, `oinstance`, `oexplain`, `odecompile`, `osbx`.

Standalone sandbox scanner binary available at `tools/osbx-standalone/`.

## Performance Notes

Batch size **35** is optimal. Key optimizations:
- Bulk `ReadMemory()` instead of per-item expressions
- Objective-C blocks for compound expressions
- Per-process caching (<0.01s on subsequent queries)

| Scenario | Time |
|----------|------|
| First run (~10K classes) | ~12s |
| Cached run | <0.01s |
