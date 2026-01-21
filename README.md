# LLDB Objective-C Automation Tools

Custom LLDB commands for working with Objective-C methods, including private symbols that aren't directly accessible.

## Features

- **obrk**: Set breakpoints using familiar Objective-C syntax: `-[ClassName selector:]`
- **osel**: Search for selectors in any Objective-C class with wildcard patterns
- **ocls**: Find and list Objective-C classes with wildcard pattern matching
- **ocall**: Call Objective-C methods directly from LLDB
- **owatch**: Set auto-logging breakpoints to watch method calls
- **opool**: Find instances of Objective-C classes in autorelease pools
- **oinstance**: Inspect Objective-C object instances with detailed ivar information
- **oinstances**: Efficiently scan memory for all instances of a class (heap, stack, segments)
- **odump**: Dump NSData contents or raw memory to a file
- **oentitlements**: Extract and display process entitlements in human-readable format
- **okeychain**: Query and list keychain items accessible to the process
- **osc**: Display dyld shared cache information (base address, size, UUID, path)
- Works with private classes and methods
- Supports both instance methods (`-`) and class methods (`+`)
- Runtime resolution using `NSClassFromString`, `NSSelectorFromString`, and `class_getMethodImplementation`
- **High-performance caching**: Instant results for repeated queries (1000x+ faster)

## Installation

### Quick Install (Recommended)

Run the installation script to copy scripts to `~/.lldb-objc/` and configure your `~/.lldbinit`:

```bash
cd /path/to/lldb-objc
./install.py
```

Scripts are installed to `~/.lldb-objc/scripts/` for a stable path. The commands will be available automatically whenever you start LLDB.

The installer automatically discovers and lists all available commands - no manual updates needed when new commands are added.

**Installation Commands:**
```bash
./install.py              # Install to ~/.lldb-objc and update ~/.lldbinit
./install.py --status     # Check installation status
./install.py --uninstall  # Remove ~/.lldb-objc and clean ~/.lldbinit
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
# List all methods in CSSymbolOwner
osel CSSymbolOwner

# Substring matching - find selectors containing "symbol"
osel CSSymbolOwner symbol

# Wildcard patterns
osel CSSymbolOwner *name*    # Selectors containing 'name'
osel CSSymbolOwner _init*    # Selectors starting with '_init'
osel CSSymbolOwner *set*     # Selectors containing 'set' anywhere

# Find specific selectors
osel CSSymbolOwner symbolWithName
osel CSSymbolOwner _internal

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
ocls CSSymbolOwner       # Exact match for "CSSymbolOwner" class (<0.01s)
ocls UIViewController    # Shows: UIViewController → UIResponder → NSObject

# Wildcard patterns (uses cache or full enumeration)
ocls CS*                 # All classes starting with "CS"
ocls *Service            # All classes ending with "Service"
ocls *Navigation*        # All classes containing "Navigation"
ocls _UI*                # All private UIKit classes

# Cache control
ocls --reload            # Refresh the cache (after loading new frameworks)
ocls --reload CS*        # Refresh and filter
ocls --clear-cache       # Clear cache for current process

# Performance tuning (for testing different batch sizes)
ocls --batch-size=50 --reload    # Use larger batches
ocls --batch-size 25 --reload    # Use smaller batches

# Verbose output (shows detailed timing breakdown)
ocls --verbose CS*               # Detailed metrics for pattern search
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

### odump - Dump Memory to File

Dump NSData contents or raw memory regions to a file.

**Syntax:**
```
odump <expr> <output_path>              # Dump NSData to file
odump <expr> <output_path> --size=N     # Dump N bytes from address
odump <expr> <output_path> --force      # Use --force for protected memory
```

**Arguments:**
- `<expr>`: Address or ObjC expression (`0x12345`, `$0`, `$arg1`, `[self data]`, `myObject.data`)
- `<output_path>`: Output file path
- `--size=N`: Raw memory mode - dump N bytes (supports hex `0x100` or decimal `256`)
- `--force`: Pass through to `memory read --force` for protected memory

**Examples:**
```
# Dump NSData to file
odump $0 /tmp/data.bin

# Dump NSData from expression
odump [self imageData] /tmp/image.bin

# Dump 256 bytes of raw memory (hex size)
odump 0x12345678 /tmp/mem.bin --size=0x100

# Dump 1024 bytes of raw memory (decimal size)
odump $myBuffer /tmp/buffer.bin --size=1024

# Force dump protected memory
odump 0xDEADBEEF /tmp/protected.bin --size=64 --force
```

**Modes:**
- **NSData mode (default)**: When `--size` is NOT provided, treats expression as NSData object and calls `[obj bytes]` and `[obj length]` via runtime
- **Raw memory mode**: When `--size=N` is provided, treats expression as start address and dumps N bytes

**Notes:**
- Silently overwrites existing output files
- Supports NSData subclasses (NSMutableData, NSConcreteData, etc.)
- Uses `memory read --outfile` internally for reliable binary output

### oentitlements - Extract Process Entitlements

Extract and display the entitlements of the current process, showing which capabilities and permissions it has.

**Syntax:**
```
oentitlements              # Show entitlements in JSON format
oentitlements --xml        # Show raw XML plist format
oentitlements --verbose    # Show detailed debug info
```

**Examples:**
```
# Display entitlements in readable JSON format
oentitlements

# Show raw XML plist
oentitlements --xml

# Debug mode with extraction details
oentitlements --verbose
```

**Output:**
```
Process Entitlements:
============================================================
{
  "application-identifier": "TEAM123.com.example.app",
  "com.apple.developer.team-identifier": "TEAM123",
  "get-task-allow": true,
  "keychain-access-groups": [
    "TEAM123.com.example.app",
    "TEAM123.shared"
  ]
}
============================================================

Keychain Access Groups (2):
  - TEAM123.com.example.app
  - TEAM123.shared
```

**Notes:**
- Uses `csops` system call for efficient extraction (falls back to `__LINKEDIT` parsing)
- Highlights keychain-access-groups which determine keychain item accessibility
- Useful for debugging keychain access issues and understanding app permissions
- Works on both iOS and macOS

### okeychain - Query Keychain Items

Query and list all keychain items accessible to the current process based on its entitlements.

**Syntax:**
```
okeychain list                      # List all accessible keychain items
okeychain list --filter=<query>     # Filter by access group or account
okeychain list --verbose            # Show detailed debug info
okeychain                           # Same as 'okeychain list'
```

**Examples:**
```
# List all keychain items accessible to the process
okeychain list

# Filter keychain items
okeychain list --filter=apple
okeychain list --filter=AuthToken

# Show verbose debug output
okeychain list --verbose

# Default to list command
okeychain
```

**Output:**
```
Found 3 keychain item(s)
============================================================

Item 1:
------------------------------------------------------------
Class: genp
  agrp: TEAM123.com.example.app
  acct: user@example.com
  svce: com.example.service
  labl: User Credentials
  v_Data: <encrypted data...>

Item 2:
------------------------------------------------------------
Class: inet
  agrp: apple
  acct: username
  v_Data: <encrypted data...>
...
```

**Keychain Classes Queried:**
- `kSecClassGenericPassword` (genp) - Generic passwords
- `kSecClassInternetPassword` (inet) - Internet passwords
- `kSecClassCertificate` (cert) - Certificates
- `kSecClassKey` (keys) - Cryptographic keys
- `kSecClassIdentity` (idnt) - Identities (cert + private key)

**Notes:**
- Only shows items the process has access to based on its entitlements
- Use `oentitlements` to see which keychain-access-groups the process can access
- Useful for debugging keychain access issues and understanding what data is stored
- The device must be unlocked for keychain access
- Works on both iOS and macOS

### osc - Dyld Shared Cache Information

Display information about the dyld shared cache used by the current process.

**Syntax:**
```
osc              # Show shared cache info
osc --verbose    # Show detailed debug info
```

**Examples:**
```
# Display shared cache information
osc

# Show with debug output
osc --verbose
```

**Output:**
```
Dyld Shared Cache Information:
======================================================================
Base Address:     0x00007ff800000000
End Address:      0x00007ff84a0c0000
Size:             1.16 GB (1,241,513,984 bytes)
UUID:             550E8400-E29B-41D4-A716-446655440000
File Path:        /System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_x86_64h

Loaded at:        0x00007ff800000000 (with ASLR slide applied)
======================================================================
```

**Information Displayed:**
- **Base Address**: Memory address where the shared cache is loaded
- **End Address**: End of the shared cache in memory
- **Size**: Total size of the shared cache (formatted as GB/MB/KB)
- **UUID**: Unique identifier for this shared cache build
- **File Path**: Location of the shared cache file on disk
- **ASLR Slide**: The base address includes the ASLR slide applied at load time

**Notes:**
- The dyld shared cache contains pre-linked system frameworks for faster app launch
- On macOS Ventura+, the cache is located at `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/`
- The UUID uniquely identifies the cache build and can be used to match symbols
- Useful for understanding memory layout and verifying which shared cache version is in use
- Works on both iOS and macOS

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

- [AGENTS.md](AGENTS.md) - Development guide for agents and contributors
- [docs/PLAN.md](docs/PLAN.md) - Roadmap, current stage, and backlog
- [docs/DESIGN.md](docs/DESIGN.md) - Architecture and planned features
- [docs/TESTING.md](docs/TESTING.md) - Testing guide and best practices
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) - Performance optimization
- [docs/UI_CONVENTIONS.md](docs/UI_CONVENTIONS.md) - UI formatting conventions
- [docs/SANDBOX_SUMMARY.md](docs/SANDBOX_SUMMARY.md) - Sandbox testing guide

## Testing

```bash
pip install -r requirements-dev.txt  # Install dependencies
pytest                               # Unit tests (fast)
./tests/run_all_tests.py --quick     # Quick integration tests
./build.sh check                     # Full pre-commit check
```

See [docs/TESTING.md](docs/TESTING.md) for the full testing guide.

## Examples

The [examples/](examples/) directory contains sample projects for testing:
- [HelloWorld](examples/HelloWorld/) - Simple Xcode project for testing LLDB commands

## Standalone Tools

The [tools/](tools/) directory contains standalone utilities:

### osbx-standalone - Sandbox Scanner

A native binary for fast sandbox filesystem scanning (~50,000+ paths/sec vs ~300 paths/sec via LLDB).

```bash
cd tools/osbx-standalone
make                                    # Build from source
./osbx-standalone --profile permissive.sb /tmp /var  # Test with custom profile
./sign-with-entitlements.sh /path/to/app.app         # Copy entitlements from app
```

See [tools/osbx-standalone/README.md](tools/osbx-standalone/README.md) and [docs/SANDBOX_SUMMARY.md](docs/SANDBOX_SUMMARY.md) for details.

## Note about sandbox_check

This is testable via `python tests/test_bootstrap_osbx.py`

```
Can we go back to sandbox_check()?
No. The parsing fix (GetSummary vs GetValueAsUnsigned) was a separate issue. The core problem is that sandbox_check() itself doesn't work from LLDB expressions:


(lldb) expr (int)sandbox_check((pid_t)getpid(), "file-write-data", 1, "/private/tmp")
(int) $0 = 1  # WRONG - returns "denied" even for allowed paths!

(lldb) expr (int)access("/private/tmp", 2)  
(int) $0 = 0  # CORRECT - allowed
sandbox_check() always returns 1 (denied) when called via LLDB expression evaluation, regardless of actual sandbox policy. We must use access().
```