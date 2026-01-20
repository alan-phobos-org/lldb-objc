# omemlayout - Product Requirements Document

## Overview

`omemlayout` is an LLDB command that displays comprehensive memory layout information for a running process, providing insight into memory regions similar to macOS `vmmap` but focused on critical regions for debugging: stacks, heap allocations, mapped binaries, and the dyld shared cache.

### Usage

```
omemlayout [--overview]
```

- **No flags**: Full detailed output with all regions, zone breakdowns, and binary listings
- **--overview**: Concise 12-16 line summary showing key memory locations and statistics

**Rationale for Overview Mode**: When debugging, developers often need quick answers to questions like "Where's the heap?", "What's the shared cache address?", or "How many threads are there?". The overview mode provides a scannable, dense format that fits on a single screen, perfect for quick orientation before diving into detailed analysis.

## Goals

1. Provide detailed stack information for all threads in the process
2. Enumerate heap regions with full malloc zone hierarchy (tiny/small/large allocations, magazines, racks)
3. Identify all mapped binaries with their text/data segments
4. Locate and display the dyld shared cache at its runtime-slid address

## Non-Goals

- Real-time memory monitoring or tracking changes over time
- Memory leak detection (use existing tools like `opool` for autorelease pool inspection)
- Full vmmap feature parity (filtering, sorting, etc.)
- Performance profiling or memory pressure analysis

## Success Criteria

When run against the `apsd` system daemon using `test_bootstrap_systemproc.py`:

1. **Stack Discovery**: Find and report stack regions for ALL threads
   - ✅ Detect minimum 1 thread stack
   - ✅ Report actual stack bounds (not just SP)
   - ✅ Handle threads with varying stack sizes

2. **Heap Completeness**: Discover all malloc zones and their internal structure
   - ✅ Enumerate all zones (default zone + any custom zones)
   - ✅ Break down each zone by allocation tier (TINY, SMALL, LARGE)
   - ✅ Report zone metadata addresses
   - ✅ Identify magazine/rack structures (depot cache levels)

3. **Binary Mapping**: List all loaded binaries with segment information
   - ✅ Report process executable
   - ✅ List all dylibs with __TEXT/__DATA segments
   - ✅ Show load addresses for each binary

4. **Shared Region**: Accurately locate dyld shared cache
   - ✅ Find shared cache base address (with ASLR slide applied)
   - ✅ Report shared cache size
   - ✅ Verify readable at reported address

5. **Overview Mode**: Provide concise summary format
   - ✅ Output fits in 12-16 lines maximum
   - ✅ Include all critical information (stacks, heap zones, binaries, shared cache)
   - ✅ Show tier breakdown for heap zones (TINY/SMALL/LARGE with sizes)
   - ✅ Display key binary addresses and main thread stack
   - ✅ Include summary totals that match full output

## Current Implementation Status

### ✅ Implemented
- Stack region discovery per thread (via SP scanning)
- Basic heap zone enumeration (malloc_default_zone)
- Shared region discovery via `_dyld_get_shared_cache_range()`

### ⚠️ Partially Implemented
- Heap zone listing (counts zones but doesn't enumerate all)
- Zone identification (basic zone ID, no magazine/rack detail)

### ❌ Not Implemented
- Mapped binary enumeration
- Heap allocation tier breakdown (TINY/SMALL/LARGE)
- Magazine/rack structure inspection
- Zone metadata and statistics
- `--overview` flag for concise output mode

## Technical Requirements

### 1. Stack Regions

**Current Approach**: Scan frame stack pointers to estimate bounds
**Required**: Full stack region enumeration including guard pages

```c
// Use Mach VM APIs to query memory regions
task_t task = /* from process */;
mach_vm_address_t address = 0;
mach_vm_size_t size;
vm_region_basic_info_data_64_t info;
mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;

kern_return_t kr = mach_vm_region(task, &address, &size,
                                   VM_REGION_BASIC_INFO_64,
                                   (vm_region_info_t)&info, &count, &obj);
```

Match regions to threads by checking if thread SP falls within region bounds.

### 2. Heap Regions - Magazine/Rack Structure

Modern `libmalloc` uses a **magazine malloc** architecture:

```
malloc_zone_t
  ├─ tiny_rack_t
  │   ├─ magazines[N]          // Per-CPU magazines
  │   │   ├─ mag_last_free_msize
  │   │   └─ mag_free_list[]   // Free object cache
  │   └─ depot                 // Full/empty magazine exchange
  ├─ small_rack_t
  │   └─ (same structure)
  └─ large allocations (direct VM)
```

**Magazine**: Thread-local cache of freed objects (fast allocation path)
**Rack**: Collection of magazines with a depot for exchange between threads
**Depot**: Centralized storage of full and empty magazines

Required API access:
```c
// Get all zones
malloc_get_all_zones(task_t task, memory_reader_t reader,
                     vm_address_t **addresses, unsigned *count);

// For each zone, access internal structure
malloc_zone_t *zone = (malloc_zone_t *)addresses[i];
// Inspect zone->tiny_rack, zone->small_rack, zone->large_allocations
```

### 3. Mapped Binaries

Enumerate using dyld APIs:
```c
// Get image count
uint32_t count = _dyld_image_count();

// For each image
for (uint32_t i = 0; i < count; i++) {
    const char *name = _dyld_get_image_name(i);
    intptr_t slide = _dyld_get_image_vmaddr_slide(i);
    const struct mach_header *header = _dyld_get_image_header(i);
    // Parse Mach-O header to get __TEXT, __DATA segments
}
```

### 4. Shared Region (dyld shared cache)

**Current**: Uses `_dyld_get_shared_cache_range()` ✅
**Enhancement**: Parse shared cache header to show internal structure:
- __TEXT segment (all framework code)
- __DATA segment (framework data)
- Slide amount from unslid base

## Sample Output

### Overview Mode (`--overview`)

Concise format showing key memory locations in 12-16 lines:

```
Memory Layout: process 12345 (apsd) - 1.4 GB virtual
  Stacks:    8 threads, 10.0 MB total (0x00016f47c000-0x00016fbe0000 range)
    Main:    Thread #0  0x00016f47c000-0x00016f87c000  4.0 MB  [rw-]
    Workers: 7 threads @ 496 KB each
  Heap:      2 zones, 134.0 MB allocated
    Zone 0:  DefaultMallocZone_0x10034c000 (TINY:6MB SMALL:64MB LARGE:64MB)
    Zone 1:  MallocHelperZone_0x10035c000 (TINY:2MB)
  Binaries:  47 images, 8.4 MB total
    Process: /usr/libexec/apsd @ 0x100000000 [__TEXT:32K __DATA:16K]
    Main:    Foundation @ 0x1a0000000, CoreFoundation @ 0x1a01a2000
  Shared:    dyld cache @ 0x1a0000000-0x1f6000000 (1.2 GB, +512MB slide)
    Segs:    __TEXT:640MB __DATA_CONST:64MB __DATA:32MB __LINKEDIT:640MB
Summary: 10MB stacks + 134MB heap + 8MB bins + 1.2GB shared = 1.4GB virtual
```

### Target Output Format (Default)

Inspired by `vmmap` but focused on debugging-relevant information:

```
Memory Layout for process 12345 (apsd)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THREAD STACKS (8 threads)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Thread #0   0x00016f47c000-0x00016f87c000      4.0 MB  [rw-]  (main thread)
Thread #1   0x00016f87c000-0x00016f8f8000    496 KB  [rw-]
Thread #2   0x00016f8f8000-0x00016f974000    496 KB  [rw-]
Thread #3   0x00016f974000-0x00016f9f0000    496 KB  [rw-]
Thread #4   0x00016f9f0000-0x00016fa6c000    496 KB  [rw-]
Thread #5   0x00016fa6c000-0x00016fae8000    496 KB  [rw-]
Thread #6   0x00016fae8000-0x00016fb64000    496 KB  [rw-]
Thread #7   0x00016fb64000-0x00016fbe0000    496 KB  [rw-]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEAP ALLOCATIONS (2 zones)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Zone 0: DefaultMallocZone_0x000000010034c000
  Metadata       0x000000010034c000-0x0000000100350000     16 KB  [rw-]

  MALLOC_TINY    0x0000000102a00000-0x0000000103000000    6.0 MB  [rw-]
    ├─ Racks:           1
    ├─ Magazines:      16  (per-CPU caches)
    ├─ Depot full:      3  magazines
    └─ Depot empty:     5  magazines

  MALLOC_SMALL   0x0000000600000000-0x0000000604000000   64.0 MB  [rw-]
    ├─ Regions:       128  (512K each)
    ├─ Racks:           1
    ├─ Magazines:      16
    ├─ Depot full:      8  magazines
    └─ Depot empty:    12  magazines

  MALLOC_LARGE   0x0000000604000000-0x0000000608000000   64.0 MB  [rw-]
    └─ Direct VM allocations (no magazine caching)

Zone 1: MallocHelperZone_0x000000010035c000
  Metadata       0x000000010035c000-0x0000000100360000     16 KB  [rw-]
  MALLOC_TINY    0x0000000103000000-0x0000000103200000    2.0 MB  [rw-]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAPPED BINARIES (47 images)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Process:
  __TEXT         0x0000000100000000-0x0000000100008000     32 KB  [r-x]
  __DATA         0x0000000100008000-0x000000010000c000     16 KB  [rw-]
  __LINKEDIT     0x000000010000c000-0x0000000100014000     32 KB  [r--]
  /usr/libexec/apsd

System Libraries:
  __TEXT         0x00000001a0000000-0x00000001a0123000   1.1 MB  [r-x]
  __DATA_CONST   0x00000001a0123000-0x00000001a0145000    136 KB  [r--]
  __DATA         0x00000001a0145000-0x00000001a0149000     16 KB  [rw-]
  __LINKEDIT     0x00000001a0149000-0x00000001a01a2000    356 KB  [r--]
  /System/Library/Frameworks/Foundation.framework/Versions/C/Foundation

  __TEXT         0x00000001a01a2000-0x00000001a0234000    584 KB  [r-x]
  __DATA_CONST   0x00000001a0234000-0x00000001a0248000     80 KB  [r--]
  /System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation

  ... (44 more libraries)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHARED REGION (dyld shared cache)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Base Address   0x00000001a0000000  (slid from 0x0000000180000000)
Slide Amount   0x0000000020000000  (512 MB)
Size           1.2 GB
Permissions    [r-x]  (text + data, read-only after fixups)

Segments:
  __TEXT         0x00000001a0000000-0x00000001c8000000    640 MB  [r-x]
  __DATA_CONST   0x00000001c8000000-0x00000001cc000000     64 MB  [r--]
  __DATA         0x00000001cc000000-0x00000001ce000000     32 MB  [rw-]
  __LINKEDIT     0x00000001ce000000-0x00000001f6000000    640 MB  [r--]
  __OBJC_RO      0x00000001f6000000-0x00000001fb000000     80 MB  [r--]
  __OBJC_RW      0x00000001fb000000-0x00000001fb800000      8 MB  [rw-]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total Stacks:      10.0 MB  (8 threads)
Total Heap:       134.0 MB  (2 zones, 3 tiers)
Total Binaries:     8.4 MB  (47 images)
Shared Cache:       1.2 GB  (system frameworks)
Other:            48.6 MB  (guards, metadata, misc)
                 ─────────
Virtual Size:       1.4 GB
```

### Minimal Viable Output

For initial implementation when magazine/rack inspection is incomplete:

**Default mode:**
```
Memory Layout for process 12345 (apsd)

STACKS (8 threads):
  Thread #0   0x00016f47c000-0x00016f87c000      4.0 MB  [rw-]
  Thread #1   0x00016f87c000-0x00016f8f8000    496 KB  [rw-]
  Thread #2   0x00016f8f8000-0x00016f974000    496 KB  [rw-]
  Thread #3   0x00016f974000-0x00016f9f0000    496 KB  [rw-]
  Thread #4   0x00016f9f0000-0x00016fa6c000    496 KB  [rw-]
  Thread #5   0x00016fa6c000-0x00016fae8000    496 KB  [rw-]
  Thread #6   0x00016fae8000-0x00016fb64000    496 KB  [rw-]
  Thread #7   0x00016fb64000-0x00016fbe0000    496 KB  [rw-]

HEAP REGIONS (2 zones):
  Zone 0      0x000000010034c000                (DefaultMallocZone)
  Zone 1      0x000000010035c000                (MallocHelperZone)

SHARED REGION (dyld shared cache):
  Region      0x00000001a0000000-0x00000001f6000000    1.2 GB  [r-x]
              (slid +512 MB from base)

MAPPED BINARIES:
  [Binary enumeration not yet implemented]
```

**Overview mode (`--overview`):**
```
Memory Layout: process 12345 (apsd)
  Stacks:    8 threads, ~10 MB total (0x00016f47c000-0x00016fbe0000 range)
    Main:    Thread #0  0x00016f47c000-0x00016f87c000  4.0 MB  [rw-]
    Workers: 7 threads @ ~500 KB each
  Heap:      2 zones detected (tier breakdown unavailable)
    Zone 0:  DefaultMallocZone_0x10034c000
    Zone 1:  MallocHelperZone_0x10035c000
  Binaries:  [enumeration not yet implemented]
  Shared:    dyld cache @ 0x1a0000000-0x1f6000000 (1.2 GB, +512MB slide)
Summary: ~10MB stacks + 2 zones + 1.2GB shared cache
```

## Implementation Plan

### Phase 1: Core Infrastructure (Current)
- ✅ Stack enumeration via SP scanning
- ✅ Basic zone discovery
- ✅ Shared cache location

### Phase 2: Complete Heap Analysis
- Enumerate all zones with `malloc_get_all_zones()`
- Query zone internal structures for TINY/SMALL/LARGE breakdown
- Access magazine/rack metadata (if exposed via public API)
- Calculate zone statistics (allocated, free, fragmentation)

### Phase 3: Binary Mapping
- Use `_dyld_image_count()` / `_dyld_get_image_name()` for binary list
- Parse Mach-O headers to extract segment information
- Display load addresses with ASLR slides

### Phase 4: Enhanced Output
- Format output similar to vmmap (aligned columns, clear sections)
- Add summary statistics
- Colorize output (using existing ANSI_DIM/ANSI_RESET)
- Implement `--overview` flag for concise 12-16 line summary

## Testing Strategy

### Unit Tests
- Mock LLDB SBProcess/SBThread for stack scanning
- Test zone structure parsing
- Validate address range formatting

### Integration Tests
Test against `bootstrap_systemproc.py` with `apsd`:

```bash
# Run LLDB against apsd system daemon
python tests/test_bootstrap_systemproc.py

# In LLDB:
# (lldb) omemlayout           # Full detailed output
# (lldb) omemlayout --overview # Concise summary
```

**Validation checklist:**
- [ ] All threads have stack regions reported
- [ ] At least one malloc zone detected
- [ ] Shared cache base address is valid (can read memory at that address)
- [ ] Zone addresses match those shown by `heap` command
- [ ] Magazine/rack counts are reasonable (>0 magazines, >=0 depot entries)
- [ ] Overview mode produces exactly 12-16 lines of output
- [ ] Overview includes all key regions (stacks, heap, binaries, shared cache)
- [ ] Overview summary line totals match detailed output

### Reference Comparison
Compare output against `vmmap <pid>`:
- Stack regions should overlap with vmmap's "Stack" entries
- Heap zones should match vmmap's "MALLOC_*" entries
- Shared cache should match vmmap's large __TEXT region (~1GB)
- Binary list should match vmmap's individual __TEXT sections

## Open Questions

1. **Magazine/Rack API Access**: Are zone internals (magazine_t, rack_t) exposed via public malloc APIs, or do we need private headers?
   - **Resolution needed**: Check `<malloc/malloc.h>` vs internal `magazine_malloc.c`

2. **Stack Guard Pages**: Should we report guard pages separately or merge with stack regions?
   - **Recommendation**: Report guards separately for accuracy (matches vmmap)

3. **Performance**: How many `EvaluateExpression()` calls are acceptable?
   - **Target**: < 50 calls for typical process (< 1 second execution time)

4. **Permissions**: Can we access system process memory maps without sudo?
   - **Known limitation**: System process attachment requires sudo/entitlements

5. **Overview Mode Detail Level**: When showing 47 binaries in overview, should we list top N or just show count?
   - **Recommendation**: Show count + 2-3 most important (process + main frameworks), others omitted for brevity

## Related Commands

- `opool` - Autorelease pool inspection
- `osbx` - Sandbox inspection
- Built-in LLDB `memory region` - Single region info
- macOS `vmmap` - Full VM map (external tool)
- macOS `heap` - Heap zone detailed analysis (external tool)

## References

- `vmmap(1)` man page
- LLDB Python API: SBProcess, SBThread, SBMemoryRegionInfo
- libmalloc source: magazine_malloc.c, nano_malloc.c
- dyld API: `_dyld_get_shared_cache_range()`, `_dyld_image_count()`
- Mach VM API: `mach_vm_region()`, `vm_region_recurse()`
