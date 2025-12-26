# LLDB Objective-C Automation Project

## Goal
Create an LLDB command that sets breakpoints on Objective-C methods using the format `-[Class selector]`, including support for private symbols.

## Approach
Since private symbols aren't directly accessible, we need to:
1. Use `NSClassFromString()` to resolve the class at runtime
2. Use `NSSelectorFromString()` to resolve the selector
3. Use `class_getMethodImplementation()` to get the actual IMP (implementation pointer)
4. Set a breakpoint on that address

## Current Status
- ✅ Initial implementation complete
- ✅ Created [objc_breakpoint.py](objc_breakpoint.py) with `obrk` command
- ✅ Debug output cleaned up and professionalized
- ✅ Command shows Class, SEL, and IMP values during resolution
- ✅ Production-ready with minimal, informative output
- ✅ Created [objc_find.py](objc_find.py) with `ofind` command for selector discovery
- ✅ Implemented pattern matching and filtering for selector search
- ✅ Support for both instance and class method enumeration
- ✅ Added versioning system (v1.0.0)
- ✅ Created automatic installation script (install.py) for .lldbinit management

## Learnings
- **Debug output needs actual values**: Don't just show if result is valid/error - need to see the actual Class/SEL/IMP values returned
- SBValue methods to use:
  - `GetValue()` - string representation of the value
  - `GetValueAsUnsigned()` - numeric value
  - `GetSummary()` - summary description
  - Need to print ALL of these to see what we're actually getting back

## Project Structure

```
lldb-objc/
├── objc_breakpoint.py          # LLDB command for setting breakpoints
├── objc_find.py                # LLDB command for finding selectors
├── version.py                  # Version information
├── install.py                  # Installation script for .lldbinit
├── VERSION                     # Version number file
├── README.md                   # Main documentation and usage guide
├── CLAUDE.md                   # Project context and implementation notes
├── docs/                       # Documentation
│   ├── IMPLEMENTATION_NOTES.md
│   ├── PLAN.md                 # Future feature roadmap
│   ├── QUICKSTART.md
│   └── research.md
├── tests/                      # Test files and test cases
│   ├── test_bootstrap.py
│   ├── test_bootstrap.sh
│   ├── test_ofind.py
│   └── test_runner.md
└── examples/                   # Example projects
    └── HelloWorld/             # Sample Xcode project for testing
```

### Installation
Use the `install.py` script to automatically configure `.lldbinit`:
```bash
./install.py              # Install to ~/.lldbinit
./install.py --status     # Check installation status
./install.py --uninstall  # Remove from ~/.lldbinit
```

### Command Syntax
```
# Set breakpoints
obrk -[ClassName selector:]
obrk +[ClassName classMethod:]

# Find selectors
ofind ClassName
ofind ClassName pattern
```

### Resolution Chain (obrk)
1. Parse input to extract class name and selector
2. Distinguish instance (`-`) vs class (`+`) methods
3. `NSClassFromString()` → Get Class pointer
4. `NSSelectorFromString()` → Get SEL pointer
5. For class methods: `object_getClass()` → Get metaclass
6. `class_getMethodImplementation()` → Get IMP address
7. `BreakpointCreateByAddress()` → Set breakpoint

### Selector Discovery Chain (ofind)
1. Parse input to extract class name and optional pattern
2. `NSClassFromString()` → Get Class pointer
3. `class_copyMethodList()` → Get list of instance methods
4. `object_getClass()` → Get metaclass
5. `class_copyMethodList()` → Get list of class methods
6. For each method: `method_getName()` → Get selector
7. `sel_getName()` → Convert SEL to string
8. Filter by pattern (case-insensitive substring match)
9. Display sorted lists of instance and class methods

## Technical Notes
- LLDB Python scripting API will be used
- Runtime resolution is necessary for private classes/methods
- Need to handle both instance and class methods

## Future Work
See [docs/PLAN.md](docs/PLAN.md) for a comprehensive roadmap of planned features and enhancements, including:
- **Immediate next steps**: Wildcard class finder (`oclasses`), wildcard support for `ofind`, and method caller (`ocall`)
- **High priority features**: Class hierarchy viewer (`oclass`), method watcher (`owatch`)
- **Advanced features**: Instance tracker, method swizzling, block inspector, and more

All new features in PLAN.md have detailed design specifications including technical approaches, resolution chains, implementation details, and example usage.
