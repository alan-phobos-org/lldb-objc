// COMPARISON: Old vs New Expression Generation
// This shows the actual C code generated for batching

// ============================================================================
// OLD APPROACH - Inline Batching (266 expressions like this)
// ============================================================================
// Expression size: ~2,000 bytes EACH
// Total parsing: 266 × 2KB = 532 KB

// Expression 1/266:
(void *)(^{
    char *buffer = (char *)malloc(144);
    if (!buffer) return (void *)0;
    unsigned int *offsets = (unsigned int *)buffer;
    char *string_data = buffer + 144;
    unsigned int current_offset = 0;

    const char *name_0 = (const char *)class_getName((Class)0x7fff8ae12345);
    if (name_0) {
        offsets[0] = current_offset;
        size_t len = (size_t)strlen(name_0) + 1;
        if (current_offset + len < 1400) {
            (void)memcpy(string_data + current_offset, name_0, len);
            current_offset += len;
        }
    } else {
        offsets[0] = 0xFFFFFFFF;
    }

    const char *name_1 = (const char *)class_getName((Class)0x7fff8ae12346);
    if (name_1) {
        offsets[1] = current_offset;
        size_t len = (size_t)strlen(name_1) + 1;
        if (current_offset + len < 1400) {
            (void)memcpy(string_data + current_offset, name_1, len);
            current_offset += len;
        }
    } else {
        offsets[1] = 0xFFFFFFFF;
    }

    const char *name_2 = (const char *)class_getName((Class)0x7fff8ae12347);
    if (name_2) {
        offsets[2] = current_offset;
        size_t len = (size_t)strlen(name_2) + 1;
        if (current_offset + len < 1400) {
            (void)memcpy(string_data + current_offset, name_2, len);
            current_offset += len;
        }
    } else {
        offsets[2] = 0xFFFFFFFF;
    }

    // ... REPEAT 32 MORE TIMES (35 total) ...

    const char *name_34 = (const char *)class_getName((Class)0x7fff8ae1237f);
    if (name_34) {
        offsets[34] = current_offset;
        size_t len = (size_t)strlen(name_34) + 1;
        if (current_offset + len < 1400) {
            (void)memcpy(string_data + current_offset, name_34, len);
            current_offset += len;
        }
    } else {
        offsets[34] = 0xFFFFFFFF;
    }

    offsets[35] = current_offset;
    return (void *)buffer;
}())

// Expression 2/266:
// ... SAME CODE, DIFFERENT POINTERS (another 2KB) ...

// Expression 3/266:
// ... SAME CODE, DIFFERENT POINTERS (another 2KB) ...

// ... AND SO ON FOR 266 EXPRESSIONS ...


// ============================================================================
// NEW APPROACH - Helper Function (95 expressions total)
// ============================================================================
// Setup: 500 bytes (once)
// Each batch: ~100 bytes (94 times)
// Total parsing: 500 + (94 × 100) = 14 KB

// Expression 1/95 - Setup (500 bytes, executed ONCE):
(void *)(^{
    // Use static variables to persist across calls
    typedef void* (*batch_get_names_fn)(void**, unsigned int);
    static batch_get_names_fn s_h = 0;
    static void **s_b = 0;

    // Define helper function (only runs once)
    if (!s_h) {
        s_h = ^void*(void** cls, unsigned int n) {
            size_t os = (n + 1) * sizeof(unsigned int);
            size_t se = 50 * n;
            char *buf = (char *)malloc(os + se);
            if (!buf) return (void *)0;

            unsigned int *off = (unsigned int *)buf;
            char *str = buf + os;
            unsigned int co = 0;

            for (unsigned int i = 0; i < n; i++) {
                if (!cls[i]) {
                    off[i] = 0xFFFFFFFF;
                    continue;
                }
                const char *nm = (const char *)class_getName((Class)cls[i]);
                if (nm) {
                    off[i] = co;
                    size_t ln = strlen(nm) + 1;
                    if (co + ln < se) {
                        memcpy(str + co, nm, ln);
                        co += ln;
                    }
                } else {
                    off[i] = 0xFFFFFFFF;
                }
            }
            off[n] = co;
            return (void *)buf;
        };
    }

    // Allocate reusable batch buffer (only runs once)
    if (!s_b) {
        s_b = (void **)malloc(100 * sizeof(void *));
    }

    // Return both pointers
    static unsigned long long r[2];
    r[0] = (unsigned long long)s_h;
    r[1] = (unsigned long long)s_b;
    return (void *)r;
}())

// Expression 2/95 - Batch 1 (~100 bytes):
(void *)(^{
    void **b=(void **)0x7fff8ae00000;
    b[0]=0x7fff8ae12345;
    b[1]=0x7fff8ae12346;
    b[2]=0x7fff8ae12347;
    b[3]=0x7fff8ae12348;
    b[4]=0x7fff8ae12349;
    // ... up to 100 classes
    b[99]=0x7fff8ae123a8;
    return ((void*(*)(void**,unsigned int))0x7fff8ae00100)(b,100);
}())

// Expression 3/95 - Batch 2 (~100 bytes):
(void *)(^{
    void **b=(void **)0x7fff8ae00000;
    b[0]=0x7fff8ae123a9;
    b[1]=0x7fff8ae123aa;
    // ... up to 100 classes
    b[99]=0x7fff8ae1240c;
    return ((void*(*)(void**,unsigned int))0x7fff8ae00100)(b,100);
}())

// ... 92 MORE BATCHES (each ~100 bytes) ...


// ============================================================================
// COMPARISON
// ============================================================================
//
// OLD: 266 expressions × 2,000 bytes = 532,000 bytes to parse
// NEW:  95 expressions × 150 bytes  =  14,600 bytes to parse
//
// Reduction: 36x less parsing overhead
// Speedup: 2.8x fewer expressions
// Efficiency: 5.7x more classes per expression
//
// ============================================================================
