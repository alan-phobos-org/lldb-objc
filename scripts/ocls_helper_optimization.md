# Expression Optimization: Define Helper Function Once

## Problem
Current approach generates ~547 expressions for 9,306 classes (~17 classes/expr).
Each batch expression is MASSIVE (~1-2KB) because it repeats logic inline for every class.

## Solution
Define a C helper function ONCE in the target process, then reuse it for all batches.

### Step 1: Define helper function (1 expression)
```c
typedef void* (*batch_get_names_fn)(void** classes, unsigned int count);

batch_get_names_fn helper = ^void*(void** classes, unsigned int count) {
    // Estimate buffer size
    size_t offset_size = (count + 1) * sizeof(unsigned int);
    size_t string_estimate = 40 * count;
    size_t buffer_size = offset_size + string_estimate;

    char *buffer = (char *)malloc(buffer_size);
    if (!buffer) return (void *)0;

    unsigned int *offsets = (unsigned int *)buffer;
    char *string_data = buffer + offset_size;
    unsigned int current_offset = 0;

    for (unsigned int i = 0; i < count; i++) {
        const char *name = (const char *)class_getName((Class)classes[i]);
        if (name) {
            offsets[i] = current_offset;
            size_t len = strlen(name) + 1;
            if (current_offset + len < string_estimate) {
                memcpy(string_data + current_offset, name, len);
                current_offset += len;
            }
        } else {
            offsets[i] = 0xFFFFFFFF;
        }
    }
    offsets[count] = current_offset;
    return (void *)buffer;
};
```

### Step 2: For each batch, just call the helper (N expressions)
Instead of generating 1-2KB of code, just:
```c
// Allocate array with class pointers (can reuse same buffer!)
void** batch = (void**)0x<batch_buffer_addr>;
batch[0] = (void*)0x<class1_ptr>;
batch[1] = (void*)0x<class2_ptr>;
// ... up to 100+ classes
batch[N] = (void*)0x<classN_ptr>;

// Call helper - TINY expression!
(void*)helper(batch, N);
```

## Impact

### Current approach:
- Expression size: ~1-2KB per batch (35 classes)
- Batch count: ~266 batches
- Total expression parsing overhead: ~266-532KB of C code to parse

### Optimized approach:
- Setup: 1 expression (~500 bytes) - define helper
- Per batch: ~50-100 bytes (just array setup + function call)
- Batch count: ~93 batches (can pack 100 classes per batch now!)
- Total: ~500 + 93*100 = ~10KB of C code to parse

### Improvement:
- **26-50x reduction in expression parsing overhead**
- **Fewer batches needed** (can pack more work per call)
- Should get to ~100-150 classes/expression

## Even Better: Pre-allocate batch buffer
Allocate ONE buffer for class pointers, reuse for all batches:
```c
void** batch_buf = malloc(100 * sizeof(void*));
```

Then each batch is just:
```c
memcpy((void*)0x<batch_buf>, (void[]){0x<cls1>, 0x<cls2>, ...}, N * 8);
(void*)helper(batch_buf, N);
```

Now each batch expression is ~20-30 bytes!

## Alternative: Use shorter names
If we can't define functions, at least use:
```c
#define G class_getName
#define M memcpy
#define S strlen
```

But defining the helper function is WAY better.
