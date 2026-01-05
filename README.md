# LLDB Objective-C Automation Tools

Custom LLDB commands for working with Objective-C methods, including private symbols that aren't directly accessible.

## Features

- **obrk**: Set breakpoints using familiar Objective-C syntax: `-[ClassName selector:]`
- **osel**: Search for selectors in any Objective-C class with wildcard patterns
- **ocls**: Find and list Objective-C classes with wildcard pattern matching
- **ocall**: Call Objective-C methods directly from LLDB
- **owatch**: Set auto-logging breakpoints to watch method calls
- **oprotos**: Find protocol conformance across all classes
- **opool**: Find instances of Objective-C classes in autorelease pools
- **oinstance**: Inspect Objective-C object instances with detailed ivar information
- Works with private classes and methods
- Supports both instance methods (`-`) and class methods (`+`)
- Runtime resolution using `NSClassFromString`, `NSSelectorFromString`, and `class_getMethodImplementation`
- **High-performance caching**: Instant results for repeated queries (1000x+ faster)

## Installation

### Quick Install (Recommended)

Run the installation script to automatically configure your `~/.lldbinit`:

```bash
cd /path/to/lldb-objc
./install.py
```

This will add the necessary commands to your `~/.lldbinit` file. The commands will be available automatically whenever you start LLDB.

**Installation Commands:**
```bash
./install.py              # Install to ~/.lldbinit
./install.py --status     # Check installation status
./install.py --uninstall  # Remove from ~/.lldbinit
```

### Manual Installation

If you prefer to manually configure your installation:

1. Load the scripts in LLDB:
```
command script import /path/to/objc_breakpoint.py
command script import /path/to/objc_sel.py
command script import /path/to/objc_cls.py
```

2. Or add to your `~/.lldbinit` file for automatic loading:
```
command script import /path/to/lldb-objc/objc_breakpoint.py
command script import /path/to/lldb-objc/objc_sel.py
command script import /path/to/lldb-objc/objc_cls.py
```

## Usage

### obrk - Set Breakpoints

Set breakpoints on Objective-C methods using familiar syntax.

**Syntax:**
```
obrk -[ClassName selector]
obrk -[ClassName selector:withArgs:]
obrk +[ClassName classMethod:]
```

**Examples:**
```
obrk -[UIViewController viewDidLoad]
obrk -[NSString stringByAppendingString:]
obrk +[NSString stringWithFormat:]
obrk -[_UIPrivateClass privateMethod:]
```

### osel - Find Selectors

Search for selectors in any Objective-C class, including private classes.

**Syntax:**
```
osel ClassName              # List all selectors
osel ClassName pattern      # Filter by pattern (substring or wildcard)
```

**Pattern Matching:**
- Simple text: case-insensitive substring match
- `*`: matches any sequence of characters (wildcard)
- `?`: matches any single character (wildcard)

**Examples:**
```
# List all methods in IDSService
osel IDSService

# Substring matching - find selectors containing "service"
osel IDSService service

# Wildcard patterns
osel IDSService *ternal      # Selectors ending with 'ternal'
osel IDSService _init*       # Selectors starting with '_init'
osel IDSService *set*        # Selectors containing 'set' anywhere

# Find specific selectors
osel IDSService serviceIdentifier
osel IDSService _internal

# Works with private classes too
osel _UINavigationBarContentView layout
osel _UINavigationBarContentView *Size*
```

### ocls - Find Classes

Find and list Objective-C classes matching patterns. Results are cached per-process for instant subsequent queries. Uses fast-path lookup for exact matches. Automatically shows class hierarchy information based on the number of matches.

**Syntax:**
```
ocls [--reload] [--clear-cache] [--verbose] [--batch-size=N] [pattern]
```

**Flags:**
- `--reload`: Force cache refresh and reload all classes from runtime
- `--clear-cache`: Clear the cache for the current process
- `--verbose`: Show detailed timing breakdown and resource usage
- `--batch-size=N` or `--batch-size N`: Set batch size for class_getName() calls (default: 35)

**Pattern Matching:**
- No wildcards: exact match (case-sensitive) - uses fast-path NSClassFromString lookup
- `*`: matches any sequence of characters (case-insensitive wildcard)
- `?`: matches any single character (case-insensitive wildcard)

**Examples:**
```
# List all classes (cached after first run - instant!)
ocls

# Exact match (fast-path - bypasses full enumeration)
ocls IDSService          # Exact match for "IDSService" class (<0.01s)
ocls UIViewController    # Shows: UIViewController → UIResponder → NSObject

# Wildcard patterns (uses cache or full enumeration)
ocls IDS*                # All classes starting with "IDS"
ocls *Service            # All classes ending with "Service"
ocls *Navigation*        # All classes containing "Navigation"
ocls _UI*                # All private UIKit classes

# Cache control
ocls --reload            # Refresh the cache (after loading new frameworks)
ocls --reload IDS*       # Refresh and filter
ocls --clear-cache       # Clear cache for current process

# Performance tuning (for testing different batch sizes)
ocls --batch-size=50 --reload    # Use larger batches
ocls --batch-size 25 --reload    # Use smaller batches

# Verbose output (shows detailed timing breakdown)
ocls --verbose IDS*              # Detailed metrics for pattern search
ocls --verbose --reload          # Detailed metrics for cache refresh
```

**Performance:**
- **Fast-path (exact match)**: <0.01 seconds (bypasses full enumeration)
- **First run with wildcards**: ~10-30 seconds for 10,000 classes
- **Cached run**: <0.01 seconds (1000x+ faster!)
- Use `--reload` when runtime state changes (new frameworks loaded, etc.)

**Output Modes (based on number of matches):**
- **1 match**: Detailed view showing full class hierarchy chain
- **2-20 matches**: Compact one-liner showing hierarchy for each class
- **21+ matches**: Simple class name list
- **--verbose**: Adds detailed timing breakdown and resource usage to any mode

### ocall - Call Methods

Call Objective-C methods directly from LLDB and see the results.

**Syntax:**
```
ocall +[ClassName classMethod]
ocall +[ClassName method:withArgs:]
ocall -[$variable selector]
```

**Examples:**
```
# Call class methods
ocall +[NSDate date]
ocall +[NSString stringWithFormat:] "Hello %@" "World"

# Call instance methods on variables
ocall -[$myString length]
ocall -[$myDict objectForKey:] "someKey"
```

### owatch - Watch Methods

Set auto-logging breakpoints that print method calls without stopping execution.

**Syntax:**
```
owatch -[ClassName selector:]
owatch +[ClassName classMethod:]
```

**Flags:**
- `--minimal`: Show only timestamp and method signature (compact)
- `--stack`: Include stack trace in the output

**Examples:**
```
# Watch method calls (default: shows args and return value)
owatch -[NSString initWithFormat:]

# Minimal output (timestamp + signature only)
owatch --minimal -[UIViewController viewDidLoad]

# Include stack traces
owatch --stack +[NSUserDefaults standardUserDefaults]
```

### oprotos - Find Protocol Conformance

Find which classes conform to a specific protocol.

**Syntax:**
```
oprotos ProtocolName       # Find conforming classes
oprotos --list [pattern]   # List available protocols
```

**Examples:**
```
# Find classes conforming to NSCoding
oprotos NSCoding

# Find NSCopying conformers
oprotos NSCopying

# List all protocols
oprotos --list

# List protocols matching pattern
oprotos --list *Delegate
oprotos --list NS*
```

### opool - Find Instances in Autorelease Pools

Find instances of an Objective-C class by scanning autorelease pools.

**Syntax:**
```
opool [--verbose] ClassName  # Find instances in autorelease pools
```

**Examples:**
```
# Find all NSDate instances in pools
opool NSDate

# Find NSString instances
opool NSString

# Show full pool debug output while searching
opool --verbose NSString

# Works with instances created via ocall
ocall +[NSDate date]
opool NSDate           # Will find the date we just created

# Find private class instances
opool _NSInlineData
```

**Flags:**
- `--verbose`: Show the raw pool contents from `_objc_autoreleasePoolPrint()` (normally suppressed)

**Notes:**
- Scans autorelease pools using `_objc_autoreleasePoolPrint()`
- Pool debug output is suppressed by default; use `--verbose` to see it
- Only finds instances that are currently in autorelease pools
- Does not scan heap or LLDB variables
- Automatically filters by class type using `isKindOfClass:`
- Does not require heap.py, works on iOS and macOS

### oinstance - Inspect Object Instances

Inspect a specific Objective-C object instance, showing detailed information including class hierarchy, instance variables, and values.

**Syntax:**
```
oinstance <address|$var|expression>      # Inspect object
```

**Examples:**
```
# Inspect a specific object by expression
oinstance (id)[NSDate date]

# Inspect by hex address
oinstance 0x123456789abc

# Inspect with LLDB variable
oinstance $0
oinstance self

# Inspect shows: class name, description, hierarchy, and all instance variables with values
```

**Inspection Output Format:**
```
ClassName (0x123456789abc)
  Object description here...

  Class Hierarchy:
    ClassName → SuperClass → NSObject

  Instance Variables (3):
    0x008  isa              0x00007fff12345678  Class (ClassName)
    0x010  _someIvar        0x0000000000000042  66 (long long)
    0x018  _objIvar         0x0000600000012340  <NSString instance>  (NSString)
```

**Notes:**
- Shows full object details including ivars, class hierarchy, and values
- Supports tagged pointers and regular heap objects
- Decodes ivar values based on Objective-C type encodings
- Works with any object address, variable, or expression

## How It Works

1. **Class Resolution**: Uses `NSClassFromString()` to find the class at runtime
2. **Selector Resolution**: Uses `NSSelectorFromString()` to get the selector
3. **Metaclass Handling**: For class methods, retrieves the metaclass using `object_getClass()`
4. **IMP Resolution**: Calls `class_getMethodImplementation()` to get the actual function pointer
5. **Breakpoint Creation**: Sets a breakpoint at the resolved address

## Requirements

- The target process must be running and stopped
- The process must have Foundation framework loaded
- Works on iOS, macOS, and other Apple platforms with Objective-C runtime

## Notes

- The script evaluates expressions in the context of the current frame, so the process must be stopped
- Breakpoints are set by address, so they'll persist even if the method is swizzled
- The breakpoint name is set to the method signature for easy identification

## Documentation

- [PLAN.md](docs/PLAN.md) - Future features and roadmap
- [PERFORMANCE.md](docs/PERFORMANCE.md) - Performance benchmarks and optimization details
- [UI_CONVENTIONS.md](docs/UI_CONVENTIONS.md) - UI formatting and display conventions

## Testing

Test files can be found in the [tests/](tests/) directory. Run all tests with:
```bash
./tests/run_all_tests.py          # Run all tests
./tests/run_all_tests.py --quick  # Run quick subset only
```

See [tests/test_runner.md](tests/test_runner.md) for more details on the test framework.

## Examples

The [examples/](examples/) directory contains sample projects for testing:
- [HelloWorld](examples/HelloWorld/) - Simple Xcode project for testing LLDB commands
