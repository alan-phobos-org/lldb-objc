#!/usr/bin/env python3
"""
Quick test to check if NSDate actually has ivars.
"""
import subprocess
import sys

# Create a simple LLDB script to test NSDate ivars
lldb_script = """
br set -n main
run
expr @import Foundation
expr (void *)NSClassFromString(@"NSDate")
expr (unsigned int *)malloc(sizeof(unsigned int))
script
import lldb
frame = lldb.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()

# Get NSDate class
class_result = frame.EvaluateExpression('(void *)NSClassFromString(@"NSDate")')
class_ptr = class_result.GetValueAsUnsigned()
print(f"NSDate class pointer: 0x{class_ptr:x}")

# Allocate count variable
count_result = frame.EvaluateExpression('(unsigned int *)malloc(sizeof(unsigned int))')
count_ptr = count_result.GetValueAsUnsigned()
print(f"Count variable: 0x{count_ptr:x}")

# Get ivar list
ivar_list_result = frame.EvaluateExpression(f'(void *)class_copyIvarList((Class)0x{class_ptr:x}, (unsigned int *)0x{count_ptr:x})')
ivar_list_ptr = ivar_list_result.GetValueAsUnsigned()
print(f"Ivar list pointer: 0x{ivar_list_ptr:x}")

# Read count
count_val_result = frame.EvaluateExpression(f'(unsigned int)(*(unsigned int *)0x{count_ptr:x})')
count_val = count_val_result.GetValueAsUnsigned()
print(f"Ivar count: {count_val}")

# Check instance size
size_result = frame.EvaluateExpression(f'(size_t)class_getInstanceSize((Class)0x{class_ptr:x})')
size_val = size_result.GetValueAsUnsigned()
print(f"Instance size: {size_val}")

# Try with __NSDate (private subclass)
private_result = frame.EvaluateExpression('(void *)NSClassFromString(@"__NSDate")')
if private_result.IsValid() and not private_result.GetError().Fail():
    private_ptr = private_result.GetValueAsUnsigned()
    if private_ptr != 0:
        print(f"\\n__NSDate class pointer: 0x{private_ptr:x}")

        # Get ivar list for __NSDate
        count2_result = frame.EvaluateExpression('(unsigned int *)malloc(sizeof(unsigned int))')
        count2_ptr = count2_result.GetValueAsUnsigned()

        ivar_list2_result = frame.EvaluateExpression(f'(void *)class_copyIvarList((Class)0x{private_ptr:x}, (unsigned int *)0x{count2_ptr:x})')
        ivar_list2_ptr = ivar_list2_result.GetValueAsUnsigned()

        count2_val_result = frame.EvaluateExpression(f'(unsigned int)(*(unsigned int *)0x{count2_ptr:x})')
        count2_val = count2_val_result.GetValueAsUnsigned()
        print(f"__NSDate ivar count: {count2_val}")

quit
quit
"""

# Write script to temp file
with open('/tmp/test_nsdate.lldb', 'w') as f:
    f.write(lldb_script)

# Run LLDB
result = subprocess.run(
    ['lldb', '/Users/alan/rc/lldb-objc/examples/HelloWorld/HelloWorld/HelloWorld', '-s', '/tmp/test_nsdate.lldb'],
    capture_output=True,
    text=True
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr, file=sys.stderr)
