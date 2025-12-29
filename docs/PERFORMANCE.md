# Performance Optimization

## Summary
| Scenario | Time |
|----------|------|
| First run (~10K classes) | ~12s |
| Cached run | <0.01s |

## Batch Size
Optimal: **35** (tested 10-100)

| Size | Time | Analysis |
|------|------|----------|
| 10 | 22s | Too many expressions |
| **35** | **12s** | Optimal |
| 100 | 16s | Parsing overhead |

## Key Optimizations
1. Bulk `ReadMemory()` instead of per-item expressions
2. Objective-C blocks for compound expressions
3. Per-process caching

## Operation Speeds
| Operation | Speed |
|-----------|-------|
| `EvaluateExpression()` | 10-50ms (slow) |
| `ReadMemory()` | <1ms (fast) |
