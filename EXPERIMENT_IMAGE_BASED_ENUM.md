# Experimental Image-Based Class Enumeration

## Overview

This document describes the experimental image-based approach for enumerating Objective-C classes, available via the `--experiment` flag in `ocls`.

## Background

The current (default) monolithic enumeration uses:
1. `objc_copyClassList(&count)` → Get array of Class pointers
2. For each class: `class_getName(class)` → Get name string (~10,000 calls for typical runtime)

This works well but requires ~10K function calls within a single expression.

## Experimental Approach

The experimental approach uses:
1. `objc_copyImageNames(&count)` → Get all loaded image paths (~200 images)
2. For each image: `objc_copyClassNamesForImage(path, &count)` → Get class name **strings directly**
3. Aggregate all class names into consolidated buffer

### Key Difference

`objc_copyClassNamesForImage` returns **strings directly** (not Class pointers), eliminating the need for ~10K `class_getName()` calls.

### Tradeoff Analysis

| Approach | API Calls | String Lookups |
|----------|-----------|----------------|
| **Standard** | 1 (copyClassList) | ~10,000 (class_getName) |
| **Experimental** | ~400 (images × 2) | 0 (strings returned directly) |

The experimental approach makes MORE API calls (~400 vs 1) but avoids ~10K string lookup operations.

## Usage

### Benchmark Standard Approach
```bash
(lldb) ocls --reload --verbose
```

Output will show:
```
Performance Summary:
  Total time:     1.23s
  Classes:        12,345 total, 12,345 matched
  Throughput:     10,037 classes/sec
  Batch size:     35
  Approach:       class-list      # ← Standard approach
```

### Benchmark Experimental Approach
```bash
(lldb) ocls --reload --verbose --experiment
```

Output will show:
```
Performance Summary:
  Total time:     0.98s
  Classes:        12,345 total, 12,345 matched
  Throughput:     12,597 classes/sec
  Batch size:     35
  Approach:       image-based     # ← Experimental approach
```

## Expected Results

Both approaches should:
- ✅ Return identical class lists
- ✅ Have similar expression counts (3 total: 1 main + 1 free + setup overhead)
- ✅ Have identical memory read counts (2: header + data)

Performance differences depend on:
- Runtime's internal optimizations for class name caching
- Whether `objc_copyClassNamesForImage` uses pre-computed string arrays
- Memory access patterns and cache locality

## Validation

Run the static validation script:
```bash
./scripts/benchmark_experiment.sh
```

This checks:
- ✅ Function implementations present
- ✅ Correct API usage
- ✅ Flag parsing works
- ✅ Python syntax valid

## Implementation Details

### Expression Structure (Experimental)

```c
(void *)(^{
    // Step 1: Get all loaded images
    unsigned int img_count = 0;
    const char **image_names = objc_copyImageNames(&img_count);

    // Step 2: First pass - calculate buffer size needed
    unsigned int total_classes = 0;
    size_t total_str_len = 0;
    for (unsigned int i = 0; i < img_count; i++) {
        unsigned int cls_count = 0;
        const char **cls_names = objc_copyClassNamesForImage(image_names[i], &cls_count);
        // Calculate sizes...
        free(cls_names);
    }

    // Step 3: Allocate consolidated buffer
    // Format: [count:4][total_len:4][offsets:(count+1)*4][strings:total_len]

    // Step 4: Second pass - copy all class names
    for (unsigned int i = 0; i < img_count; i++) {
        const char **cls_names = objc_copyClassNamesForImage(image_names[i], &cls_count);
        // Copy strings to buffer...
        free(cls_names);
    }

    free(image_names);
    return buffer;
}())
```

### Buffer Format

Both approaches use the same buffer format for consistency:
```
[count: 4 bytes]              # Total number of classes
[total_len: 4 bytes]          # Total string data length
[offsets: (count+1)*4 bytes]  # Offset array (last = total_len)
[strings: total_len bytes]    # Concatenated null-terminated strings
```

## Why This Might Be Faster

1. **Pre-cached strings**: The runtime may maintain per-image class name lists in memory
2. **Better locality**: Classes from the same image are adjacent in memory
3. **Fewer pointer dereferences**: Direct string access vs pointer→name lookups
4. **Optimized runtime path**: `objc_copyClassNamesForImage` may be more optimized for bulk retrieval

## Why This Might Be Slower

1. **More function calls**: ~400 API calls vs 1 (though within same expression)
2. **Two-pass iteration**: Needs to iterate images twice (size calculation, then data copy)
3. **Additional memory allocations**: One allocation per image vs one allocation total

## Next Steps

1. **Benchmark on real workloads**: Test with typical iOS/macOS debugging scenarios
2. **Profile expression parsing time**: LLDB expression parsing could dominate
3. **Consider hybrid approach**: Auto-select based on image count
4. **Measure cache effects**: Second/third runs might show different patterns

## Questions to Answer

- [ ] Is `objc_copyClassNamesForImage` noticeably faster than `class_getName`?
- [ ] Does the runtime cache class name lists per-image?
- [ ] What's the expression parsing overhead for each approach?
- [ ] Do multiple image iterations hurt cache performance?
- [ ] Should we auto-select based on heuristics (image count, class count)?

## Related Code

- Implementation: [scripts/objc_cls.py](scripts/objc_cls.py#L1512-1619)
- Standard approach: [scripts/objc_cls.py](scripts/objc_cls.py#L1622-1691)
- Integration point: [scripts/objc_cls.py](scripts/objc_cls.py#L2068-2076)
- Tests: [scripts/benchmark_experiment.sh](scripts/benchmark_experiment.sh)
