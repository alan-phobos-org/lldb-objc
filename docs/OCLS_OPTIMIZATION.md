# OCLS Performance Optimization

## Current Performance (After Optimizations)

| Scenario | Time | Method |
|----------|------|--------|
| Exact match (e.g., `NSObject`) | <0.01s | Fast-path via NSClassFromString |
| First enumeration (10K classes) | ~6-7s | Single-pass monolithic expression |
| Cached queries | <0.01s | In-memory cache per process |
| Wildcard patterns (e.g., `NS*`) | ~6-7s | Full enumeration + Python filter |

## Completed Optimizations

### 1. Single-Pass Monolithic Expression (~2x speedup)
**Changed:** [objc_cls.py:1507-1587](scripts/objc_cls.py:1507-1587)

Pre-allocate string buffer (50 bytes/class avg) to eliminate second pass:
- **Before:** 20K `class_getName()` calls (2 passes × 10K classes)
- **After:** 10K calls (single pass)
- **Time:** 11s → 6-7s

### 2. Test Suite Optimization (~5x speedup)
**Changed:** Removed redundant `--reload` flags from tests

- **Before:** 64s total (5-6 full enumerations)
- **After:** 12-15s (1 enumeration + cache hits)

### 3. Exact Match Fast-Path
Uses `NSClassFromString()` to bypass enumeration entirely (2 expressions vs 10K).

## Key Technique from Apple's heap.py

**In-process filtering via C callbacks** - [reference/heap.py:906-970](reference/heap.py:906-970)

heap.py implements pattern matching **inside the C expression**, returning only matches:
```c
range_callback_t callback = [](task_t task, void *baton, ...) {
    if (matches(item, pattern)) {  // Filter in C
        baton->matches[baton->num_matches++] = item;
    }
};
```

## Future Optimization: In-Expression Wildcard Filtering

### Problem
Current approach transfers **all** 10K class names (~300KB) then filters in Python.

### Solution
Generate C code that filters during enumeration, returning only matches.

### Expected Impact (for `CS*` → 50 matches out of 10K)

| Metric | Current | With C Filter | Improvement |
|--------|---------|---------------|-------------|
| Data transfer | ~300KB | ~6KB | **50x less** |
| Python filtering | 10K comparisons | 0 | **eliminated** |
| Total time | ~6-7s | ~1-2s | **3-5x faster** |

### Implementation Approach

**Phase 1: Simple prefix patterns** (`CS*`, `NS*`)
- Easiest to implement (just `strncmp` in C)
- Covers most common use cases
- Huge data transfer reduction

**Phase 2: Full wildcard support** (`*Navigation*`, `*View?`)
- Requires complete wildcard matcher in C (~50 lines)
- Diminishing returns vs Phase 1

### Code Changes Required

Modify `build_monolithic_class_enumeration_expr()` in [objc_cls.py:1507](scripts/objc_cls.py:1507):

```python
def build_monolithic_class_enumeration_expr(pattern: Optional[str] = None):
    if pattern and is_simple_prefix(pattern):  # "CS*"
        return build_prefix_filtered_expr(pattern)
    elif pattern and has_wildcards(pattern):  # "*Nav*"
        return build_wildcard_filtered_expr(pattern)
    else:
        return build_full_enumeration_expr()  # Current
```

Expression template for prefix filtering:
```c
// For pattern "CS*":
for (unsigned int i = 0; i < count; i++) {
    const char *name = class_getName(classes[i]);
    if (name && strncmp(name, "CS", 2) == 0) {  // C filtering
        // Copy to matches buffer
    }
}
// Return compact buffer with only matches
```

## When to Implement

**High value:** Users frequently search for framework classes:
- `NS*` (Foundation classes)
- `UI*` (UIKit classes)
- `CS*` (CoreSymbolication)

**Metrics to track:**
- Pattern type distribution (prefix vs complex wildcards)
- Average match count per pattern
- If >80% are simple prefixes → implement Phase 1

## Alternative: objc_copyClassNamesForImage

Already implemented for `--dylib` filtering - see [objc_cls.py:1329-1410](scripts/objc_cls.py:1329-1410).

Uses `objc_copyClassNamesForImage()` to get classes from specific frameworks (~1000x faster than filtering post-enumeration).

**Insight:** Runtime has optimized functions for specific filters - leverage them when possible.

## Summary

**Completed:** Test suite 5x faster, enumeration 2x faster via single-pass monolithic expression.

**Next opportunity:** In-expression wildcard filtering (3-5x speedup for sparse patterns) inspired by heap.py's callback-based filtering approach.

**Tradeoff:** Implementation complexity vs speedup magnitude - worthwhile if prefix patterns are common.
