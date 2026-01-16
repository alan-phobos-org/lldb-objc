# Performance Optimization

## Summary
| Scenario | Time |
|----------|------|
| First run (~10K classes) | ~1-3s |
| Cached run | <0.01s |
| `--dylib` filter | <0.5s |

## Key Optimizations

### 1. Monolithic Expression (ocls)
Single expression enumerates ALL classes in one shot:
- Calls `objc_copyClassList()` internally
- Two-pass: calculate exact sizes, then copy
- Returns packed buffer: `[count][total_len][offsets][strings]`
- Result: 2 expressions + 2 memory reads vs ~1000+ roundtrips

### 2. Image-Based Enumeration (--dylib)
**Critical insight**: When filtering by dylib, use `objc_copyClassNamesForImage()` per matching module instead of enumerating all classes then filtering.

| Approach | Expressions | Use Case |
|----------|-------------|----------|
| Old: enumerate all → filter | O(2N) where N=matched classes | Never |
| New: match modules → query per image | O(2M) where M=modules (~1-5) | Always |

Example: `ocls --dylib *Foundation* NS*`
- Old: ~2000 expressions (1000 classes × 2 calls each)
- New: ~2 expressions (1 matching module)
- **Speedup: ~1000x**

Implementation:
1. `target.module_iter()` in Python (instant, no LLDB overhead)
2. Match module paths against dylib pattern
3. `objc_copyClassNamesForImage(path)` once per matching module

### 3. Per-Process Caching
Cache invalidated on process restart. Use `--reload` to force refresh.

### 4. Bulk Memory Reads
`ReadMemory()` is ~50x faster than `EvaluateExpression()`.

## Operation Speeds
| Operation | Speed |
|-----------|-------|
| `EvaluateExpression()` | 10-50ms (slow) |
| `ReadMemory()` | <1ms (fast) |
| `target.module_iter()` | <1ms (pure Python) |

## Legacy: Batch Size
Only used in fallback path when monolithic expression fails.
Optimal: **35** (tested 10-100)
