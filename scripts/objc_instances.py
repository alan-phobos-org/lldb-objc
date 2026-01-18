#!/usr/bin/env python3
"""
LLDB script for finding instances of Objective-C classes in memory.
Usage: oinstances [options] <ClassName>
       oinstances NSString              # Find all NSString instances in heap
       oinstances NSDate --stack        # Include stack scanning
       oinstances UIViewController -M 100  # Find up to 100 instances
       oinstances NSObject --vm-regions # Scan all VM regions (comprehensive)

This command efficiently scans memory for instances of the specified class
(including subclasses) using native C code execution for maximum performance.

Adapted from LLDB's heap.py for optimal memory scanning efficiency.
"""

from __future__ import annotations

import lldb
from typing import Any, Dict

from objc_core import ANSI_DIM, ANSI_RESET
from objc_utils import evaluate_expression, register_command, require_stopped_process

_initialized = False


def get_thread_stack_ranges_struct(process: lldb.SBProcess) -> str:
    """
    Generate C code defining stack bounds for all threads.
    Adapted from heap.py lines 1171-1205.
    """
    stack_dicts = []
    if process:
        i = 0
        for thread in process:
            min_sp = thread.frame[0].sp
            max_sp = min_sp
            for frame in thread.frames:
                sp = frame.sp
                if sp < min_sp:
                    min_sp = sp
                if sp > max_sp:
                    max_sp = sp
            if min_sp < max_sp:
                stack_dicts.append({"tid": thread.GetThreadID(), "base": min_sp, "size": max_sp - min_sp, "index": i})
                i += 1

    stack_dicts_len = len(stack_dicts)
    if stack_dicts_len > 0:
        result = f"""
#define NUM_STACKS {stack_dicts_len}
#define STACK_RED_ZONE_SIZE {process.target.GetStackRedZoneSize()}
typedef struct thread_stack_t {{ uint64_t tid, base, size; }} thread_stack_t;
thread_stack_t stacks[NUM_STACKS];"""
        for stack_dict in stack_dicts:
            result += f"""
stacks[{stack_dict["index"]}].tid  = 0x{stack_dict["tid"]:x};
stacks[{stack_dict["index"]}].base = 0x{stack_dict["base"]:x};
stacks[{stack_dict["index"]}].size = 0x{stack_dict["size"]:x};"""
        return result
    else:
        return ""


def get_sections_ranges_struct(process: lldb.SBProcess) -> str:
    """
    Generate C code defining all data-containing segments.
    Adapted from heap.py lines 1208-1238.
    """
    target = process.target
    segment_dicts = []

    for module in target.modules:
        for sect_idx in range(module.GetNumSections()):
            section = module.GetSectionAtIndex(sect_idx)
            if not section:
                break
            name = section.name
            # Skip read-only text and metadata sections
            if name not in ["__TEXT", "__LINKEDIT", "__PAGEZERO"]:
                base = section.GetLoadAddress(target)
                size = section.GetByteSize()
                if base != lldb.LLDB_INVALID_ADDRESS and size > 0:
                    segment_dicts.append({"base": base, "size": size})

    segment_dicts_len = len(segment_dicts)
    if segment_dicts_len > 0:
        result = f"""
#define NUM_SEGMENTS {segment_dicts_len}
typedef struct segment_range_t {{ uint64_t base; uint32_t size; }} segment_range_t;
segment_range_t segments[NUM_SEGMENTS];"""
        for idx, segment_dict in enumerate(segment_dicts):
            result += f"""
segments[{idx}].base = 0x{segment_dict["base"]:x};
segments[{idx}].size = 0x{segment_dict["size"]:x};"""
        return result
    else:
        return ""


def get_iterate_memory_expr(
    process: lldb.SBProcess,
    class_ptr: int,
    max_matches: int,
    search_heap: bool,
    search_stack: bool,
    search_segments: bool,
    search_vm_regions: bool,
) -> str:
    """
    Generate C expression to scan memory for class instances.
    Adapted from heap.py's get_iterate_memory_expr and objc_refs.

    This generates C code that will be compiled and executed in the target
    process for maximum efficiency.
    """

    # Common type definitions (from heap.py lines 32-40)
    expr = """
typedef unsigned natural_t;
typedef uintptr_t vm_size_t;
typedef uintptr_t vm_address_t;
typedef natural_t task_t;
typedef int kern_return_t;
#define KERN_SUCCESS 0
typedef void (*range_callback_t)(task_t task, void *baton, unsigned type, uintptr_t ptr_addr, uintptr_t ptr_size);
"""

    # Define match structure to hold results
    expr_prefix = """
struct $objc_instance_match {
    void *addr;
    uintptr_t size;
    uintptr_t type;
};
"""
    expr += expr_prefix

    if search_vm_regions:
        # VM regions scanning (heap.py lines 41-108)
        expr += """
typedef int vm_prot_t;
typedef unsigned int vm_inherit_t;
typedef unsigned long long memory_object_offset_t;
typedef unsigned int boolean_t;
typedef int vm_behavior_t;
typedef uint32_t vm32_object_id_t;
typedef natural_t mach_msg_type_number_t;
typedef uint64_t mach_vm_address_t;
typedef uint64_t mach_vm_offset_t;
typedef uint64_t mach_vm_size_t;
typedef uint64_t vm_map_offset_t;
typedef uint64_t vm_map_address_t;
typedef uint64_t vm_map_size_t;
#define VM_PROT_NONE ((vm_prot_t) 0x00)
#define VM_PROT_READ ((vm_prot_t) 0x01)
#define VM_PROT_WRITE ((vm_prot_t) 0x02)
#define VM_PROT_EXECUTE ((vm_prot_t) 0x04)
typedef struct vm_region_submap_short_info_data_64_t {
    vm_prot_t protection;
    vm_prot_t max_protection;
    vm_inherit_t inheritance;
    memory_object_offset_t offset;
    unsigned int user_tag;
    unsigned int ref_count;
    unsigned short shadow_depth;
    unsigned char external_pager;
    unsigned char share_mode;
    boolean_t is_submap;
    vm_behavior_t behavior;
    vm32_object_id_t object_id;
    unsigned short user_wired_count;
} vm_region_submap_short_info_data_64_t;
#define VM_REGION_SUBMAP_SHORT_INFO_COUNT_64 \\
    ((mach_msg_type_number_t)(sizeof(vm_region_submap_short_info_data_64_t)/sizeof(int)))"""
    else:
        # Targeted scanning of heap/stack/segments
        if search_stack:
            expr += get_thread_stack_ranges_struct(process)
        if search_segments:
            expr += get_sections_ranges_struct(process)

    # Initialize the callback structure for finding ObjC instances
    # Adapted from objc_refs (heap.py lines 1378-1441)
    expr += f"""
#define MAX_MATCHES {max_matches}
typedef int (*compare_callback_t)(const void *a, const void *b);
typedef struct callback_baton_t {{
    range_callback_t callback;
    compare_callback_t compare_callback;
    unsigned num_matches;
    $objc_instance_match matches[MAX_MATCHES];
    void *target_class;
    Class classes[4096];  // Room for all classes in process
    int num_classes;
}} callback_baton_t;

compare_callback_t compare_callback = [](const void *a, const void *b) -> int {{
    Class a_ptr = *(Class *)a;
    Class b_ptr = *(Class *)b;
    if (a_ptr < b_ptr) return -1;
    if (a_ptr > b_ptr) return +1;
    return 0;
}};

typedef Class (*class_getSuperclass_type)(void *isa);

range_callback_t range_callback = [](task_t task, void *baton, unsigned type,
                                      uintptr_t ptr_addr, uintptr_t ptr_size) -> void {{
    class_getSuperclass_type class_getSuperclass_impl = (class_getSuperclass_type)class_getSuperclass;
    callback_baton_t *lldb_info = (callback_baton_t *)baton;

    // Check if this memory region could contain an ObjC object (at least pointer size)
    if (sizeof(Class) <= ptr_size) {{
        Class *curr_class_ptr = (Class *)ptr_addr;

        // Use binary search to check if this looks like a valid class pointer
        Class *matching_class_ptr = (Class *)bsearch(curr_class_ptr,
                                                      (const void *)lldb_info->classes,
                                                      lldb_info->num_classes,
                                                      sizeof(Class),
                                                      lldb_info->compare_callback);

        if (matching_class_ptr) {{
            bool match = false;
            if (lldb_info->target_class) {{
                Class isa = *curr_class_ptr;
                if (lldb_info->target_class == isa)
                    match = true;
                else {{
                    // Check superclass hierarchy for subclass matches
                    Class super = class_getSuperclass_impl(isa);
                    while (super) {{
                        if (super == lldb_info->target_class) {{
                            match = true;
                            break;
                        }}
                        super = class_getSuperclass_impl(super);
                    }}
                }}
            }}
            else
                match = true;

            if (match && lldb_info->num_matches < MAX_MATCHES) {{
                lldb_info->matches[lldb_info->num_matches].addr = (void*)ptr_addr;
                lldb_info->matches[lldb_info->num_matches].size = ptr_size;
                lldb_info->matches[lldb_info->num_matches].type = type;
                ++lldb_info->num_matches;
            }}
        }}
    }}
}};

callback_baton_t baton = {{ range_callback, compare_callback, 0, {{0}}, (void *)0x{class_ptr:x}, {{0}}, 0 }};

// Get all classes in the process and sort them for binary search
baton.num_classes = (int)objc_getClassList(baton.classes, sizeof(baton.classes)/sizeof(Class));
(void)qsort(baton.classes, baton.num_classes, sizeof(Class), compare_callback);
"""

    # Now add the actual memory scanning code
    if search_vm_regions:
        # Comprehensive VM region scanning (heap.py lines 78-108)
        expr += """
task_t task = (task_t)mach_task_self();
mach_vm_address_t vm_region_base_addr;
mach_vm_size_t vm_region_size;
natural_t vm_region_depth;
vm_region_submap_short_info_data_64_t vm_region_info;
kern_return_t err;

for (vm_region_base_addr = 0, vm_region_size = 1; vm_region_size != 0; vm_region_base_addr += vm_region_size) {
    mach_msg_type_number_t vm_region_info_size = VM_REGION_SUBMAP_SHORT_INFO_COUNT_64;
    err = (kern_return_t)mach_vm_region_recurse(task,
                                                 &vm_region_base_addr,
                                                 &vm_region_size,
                                                 &vm_region_depth,
                                                 &vm_region_info,
                                                 &vm_region_info_size);
    if (err)
        break;

    // Check all read + write regions
    if (vm_region_info.protection & VM_PROT_WRITE &&
        vm_region_info.protection & VM_PROT_READ) {
        baton.callback(task, &baton, 64, vm_region_base_addr, vm_region_size);
    }
}"""
    else:
        # Targeted scanning
        if search_heap:
            # Heap scanning using malloc zones (heap.py lines 116-159)
            expr += """
#define MALLOC_PTR_IN_USE_RANGE_TYPE 1
typedef struct vm_range_t {
    vm_address_t address;
    vm_size_t size;
} vm_range_t;
typedef kern_return_t (*memory_reader_t)(task_t task, vm_address_t remote_address, vm_size_t size, void **local_memory);
typedef void (*vm_range_recorder_t)(task_t task, void *baton, unsigned type, vm_range_t *range, unsigned size);
typedef struct malloc_introspection_t {
    kern_return_t (*enumerator)(task_t task, void *, unsigned type_mask,
                                 vm_address_t zone_address, memory_reader_t reader,
                                 vm_range_recorder_t recorder);
} malloc_introspection_t;
typedef struct malloc_zone_t {
    void *reserved1[12];
    struct malloc_introspection_t *introspect;
} malloc_zone_t;

memory_reader_t task_peek = [](task_t task, vm_address_t remote_address,
                                vm_size_t size, void **local_memory) -> kern_return_t {
    *local_memory = (void*) remote_address;
    return KERN_SUCCESS;
};

vm_address_t *zones = 0;
unsigned int num_zones = 0;
task_t task = 0;
kern_return_t err = (kern_return_t)malloc_get_all_zones(task, task_peek, &zones, &num_zones);

if (KERN_SUCCESS == err) {
    for (unsigned int i=0; i<num_zones; ++i) {
        const malloc_zone_t *zone = (const malloc_zone_t *)zones[i];
        if (zone && zone->introspect)
            zone->introspect->enumerator(task,
                                         &baton,
                                         MALLOC_PTR_IN_USE_RANGE_TYPE,
                                         (vm_address_t)zone,
                                         task_peek,
                                         [](task_t task, void *baton, unsigned type,
                                            vm_range_t *ranges, unsigned size) -> void {
                                             range_callback_t callback = ((callback_baton_t *)baton)->callback;
                                             for (unsigned i=0; i<size; ++i) {
                                                 callback(task, baton, type, ranges[i].address, ranges[i].size);
                                             }
                                         });
    }
}"""

        if search_stack:
            # Stack scanning (heap.py lines 161-171)
            expr += """
#ifdef NUM_STACKS
// Scan thread stack ranges
for (uint32_t i=0; i<NUM_STACKS; ++i) {
    baton.callback((task_t)0, &baton, 8, stacks[i].base, stacks[i].size);
    if (STACK_RED_ZONE_SIZE > 0) {
        baton.callback((task_t)0, &baton, 16, stacks[i].base - STACK_RED_ZONE_SIZE, STACK_RED_ZONE_SIZE);
    }
}
#endif"""

        if search_segments:
            # Segment scanning (heap.py lines 173-179)
            expr += """
#ifdef NUM_SEGMENTS
// Scan all data segments
for (uint32_t i=0; i<NUM_SEGMENTS; ++i)
    baton.callback((task_t)0, &baton, 32, segments[i].base, segments[i].size);
#endif"""

    # Return the matches array
    expr += """
if (baton.num_matches < MAX_MATCHES)
    baton.matches[baton.num_matches].addr = 0;  // Null-terminate
baton.matches"""

    return expr


def find_instances_in_memory(
    frame: lldb.SBFrame,
    class_name: str,
    max_matches: int = 32,
    search_heap: bool = True,
    search_stack: bool = False,
    search_segments: bool = False,
    search_vm_regions: bool = False,
    verbose: bool = False,
) -> list:
    """
    Find all instances of a class in memory using efficient C code execution.

    Returns list of (address, class_name, description) tuples.
    """
    process = frame.GetThread().GetProcess()

    # Get the class pointer
    class_expr = f'(Class)NSClassFromString(@"{class_name}")'
    class_result = evaluate_expression(frame, class_expr)

    if not class_result.IsValid() or class_result.GetError().Fail():
        return []

    class_ptr = class_result.GetValueAsUnsigned()
    if class_ptr == 0:
        return []

    # Generate the memory scanning expression
    expr = get_iterate_memory_expr(
        process, class_ptr, max_matches, search_heap, search_stack, search_segments, search_vm_regions
    )

    if verbose:
        print("=== Generated C Expression ===")
        print(expr)
        print("=== End Expression ===\n")

    # Execute the expression
    expr_options = lldb.SBExpressionOptions()
    expr_options.SetIgnoreBreakpoints(True)
    expr_options.SetFetchDynamicValue(lldb.eNoDynamicValues)
    expr_options.SetTimeoutInMicroSeconds(30 * 1000 * 1000)  # 30 second timeout
    expr_options.SetTryAllThreads(False)
    expr_options.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)

    expr_sbvalue = frame.EvaluateExpression(expr, expr_options)

    if not expr_sbvalue.error.Success():
        if verbose:
            print(f"Expression error: {expr_sbvalue.error}")
        return []

    # Parse results
    instances = []
    match_value = lldb.value(expr_sbvalue)
    i = 0

    while True:
        match_entry = match_value[i]
        i += 1

        if i > max_matches:
            break

        obj_addr = match_entry.addr.sbvalue.unsigned
        if obj_addr == 0:
            break

        # Get actual class name for this instance
        class_expr = f"(const char *)class_getName((Class)object_getClass((id)0x{obj_addr:x}))"
        class_result = evaluate_expression(frame, class_expr)

        actual_class = class_name
        if class_result.IsValid() and not class_result.GetError().Fail():
            class_name_ptr = class_result.GetValueAsUnsigned()
            if class_name_ptr != 0:
                error = lldb.SBError()
                class_bytes = process.ReadCStringFromMemory(class_name_ptr, 256, error)
                if error.Success() and class_bytes:
                    actual_class = class_bytes

        # Get description
        desc_expr = f"(const char *)[[(id)0x{obj_addr:x} description] UTF8String]"
        desc_result = evaluate_expression(frame, desc_expr)

        description = ""
        if desc_result.IsValid() and not desc_result.GetError().Fail():
            desc_ptr = desc_result.GetValueAsUnsigned()
            if desc_ptr != 0:
                error = lldb.SBError()
                desc_bytes = process.ReadCStringFromMemory(desc_ptr, 256, error)
                if error.Success() and desc_bytes:
                    # Collapse whitespace for single-line display
                    description = " ".join(desc_bytes.split())
                    if len(description) > 80:
                        description = description[:77] + "..."

        instances.append((obj_addr, actual_class, description))

    return instances


def find_instances_command(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    LLDB command to find all instances of an Objective-C class in memory.

    Usage: oinstances [options] <ClassName>
    """
    stopped = require_stopped_process(debugger, result)
    if not stopped:
        return
    frame, process = stopped

    # Parse arguments
    args = command.strip().split() if command.strip() else []

    # Parse options
    max_matches = 32
    search_heap = True
    search_stack = False
    search_segments = False
    search_vm_regions = False
    verbose = False

    class_name = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-M" or arg == "--max-matches":
            if i + 1 < len(args):
                try:
                    max_matches = int(args[i + 1])
                    i += 2
                    continue
                except ValueError:
                    result.SetError(f"Invalid value for {arg}: {args[i + 1]}")
                    return
            else:
                result.SetError(f"{arg} requires a value")
                return
        elif arg == "--stack":
            search_stack = True
            i += 1
        elif arg == "--segments":
            search_segments = True
            i += 1
        elif arg == "--vm-regions" or arg == "-V":
            search_vm_regions = True
            search_heap = False
            search_stack = False
            search_segments = False
            i += 1
        elif arg == "--ignore-heap":
            search_heap = False
            i += 1
        elif arg == "--verbose" or arg == "-v":
            verbose = True
            i += 1
        elif not arg.startswith("-"):
            class_name = arg
            i += 1
        else:
            result.SetError(f"Unknown option: {arg}")
            return

    if not class_name:
        result.SetError(
            "Usage: oinstances [options] <ClassName>\n"
            "Options:\n"
            "  -M, --max-matches N  Maximum instances to find (default: 32)\n"
            "  --stack              Also search thread stacks\n"
            "  --segments           Also search data segments\n"
            "  -V, --vm-regions     Search all VM regions (comprehensive)\n"
            "  --ignore-heap        Don't search heap (use with --stack/--segments)\n"
            "  -v, --verbose        Show debug output"
        )
        return

    # Find instances
    instances = find_instances_in_memory(
        frame, class_name, max_matches, search_heap, search_stack, search_segments, search_vm_regions, verbose
    )

    if not instances:
        print(f"No instances of {class_name} found")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    # Display results
    for obj_addr, actual_class, description in instances:
        # Format: dimmed_address  class  description
        addr_str = f"{ANSI_DIM}0x{obj_addr:016x}{ANSI_RESET}"

        if description:
            print(f"{addr_str}  {actual_class}  {description}")
        else:
            print(f"{addr_str}  {actual_class}")

    # Show count
    if len(instances) >= max_matches:
        print(f"\nFound {len(instances)} instances (limit reached, use -M to increase)")
    else:
        print(f"\nFound {len(instances)} instance{'s' if len(instances) != 1 else ''}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the oinstances command when this module is loaded in LLDB."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    register_command(
        debugger,
        "oinstances",
        "find_instances_command",
        __name__,
        "Find class instances in memory",
        "Find class instances in memory",
    )
