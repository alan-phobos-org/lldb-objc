# Quick Start Guide

## Installation

Add to `~/.lldbinit`:
```bash
command script import ~/rc/lldb-objc/objc_breakpoint.py
command script import ~/rc/lldb-objc/objc_find.py
```

Or load manually in LLDB:
```
(lldb) command script import /Users/alan/rc/lldb-objc/objc_breakpoint.py
(lldb) command script import /Users/alan/rc/lldb-objc/objc_find.py
```

## Quick Reference

### Find Methods (ofind)
```bash
# Explore what's available
ofind IDSService                    # List all methods
ofind IDSService service            # Find methods matching "service"
ofind IDSService serviceIdentifier  # Find specific method
ofind IDSService _internal          # Find private methods/ivars

# Works with any class
ofind NSString                      # Public class
ofind _UINavigationBar              # Private class
```

### Set Breakpoints (obrk)
```bash
# Once you found the method with ofind, break on it
obrk -[IDSService serviceIdentifier]
obrk -[IDSService _internal]
obrk +[IDSService sharedInstance]   # Class method (note the +)
```

## Typical Workflow

1. **Discover** what methods exist:
   ```
   ofind IDSService
   ```

2. **Search** for specific functionality:
   ```
   ofind IDSService service
   ```

3. **Set breakpoint** on interesting method:
   ```
   obrk -[IDSService serviceIdentifier]
   ```

4. **Continue** and hit the breakpoint:
   ```
   continue
   ```

## Testing with IDSService

```bash
# Start your app in LLDB
lldb /Applications/Messages.app

# Set a breakpoint and run
br set -n main
run

# Once stopped, try these commands:
ofind IDSService
ofind IDSService serviceIdentifier
ofind IDSService _internal
obrk -[IDSService serviceIdentifier]
continue
```

## Expected Results

When you run `ofind IDSService`, you should see:
- **Instance methods**: Including `serviceIdentifier`, `_internal`, and others
- **Class methods**: Likely initialization and factory methods
- Total count of methods found

When you run `obrk -[IDSService serviceIdentifier]`, you should see:
- Class resolution with pointer address
- SEL resolution with pointer address
- IMP resolution with function pointer
- Breakpoint number and confirmation
