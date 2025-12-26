# LLDB Objective-C Automation Tools

Custom LLDB commands for working with Objective-C methods, including private symbols that aren't directly accessible.

## Features

- **obrk**: Set breakpoints using familiar Objective-C syntax: `-[ClassName selector:]`
- **ofind**: Search for selectors in any Objective-C class
- Works with private classes and methods
- Supports both instance methods (`-`) and class methods (`+`)
- Runtime resolution using `NSClassFromString`, `NSSelectorFromString`, and `class_getMethodImplementation`

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
command script import /path/to/objc_find.py
```

2. Or add to your `~/.lldbinit` file for automatic loading:
```
command script import /path/to/lldb-objc/objc_breakpoint.py
command script import /path/to/lldb-objc/objc_find.py
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

### ofind - Find Selectors

Search for selectors in any Objective-C class, including private classes.

**Syntax:**
```
ofind ClassName              # List all selectors
ofind ClassName pattern      # Filter by pattern (substring or wildcard)
```

**Pattern Matching:**
- Simple text: case-insensitive substring match
- `*`: matches any sequence of characters (wildcard)
- `?`: matches any single character (wildcard)

**Examples:**
```
# List all methods in IDSService
ofind IDSService

# Substring matching - find selectors containing "service"
ofind IDSService service

# Wildcard patterns
ofind IDSService *ternal      # Selectors ending with 'ternal'
ofind IDSService _init*       # Selectors starting with '_init'
ofind IDSService *set*        # Selectors containing 'set' anywhere

# Find specific selectors
ofind IDSService serviceIdentifier
ofind IDSService _internal

# Works with private classes too
ofind _UINavigationBarContentView layout
ofind _UINavigationBarContentView *Size*
```

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

- [QUICKSTART.md](docs/QUICKSTART.md) - Quick start guide
- [IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md) - Technical implementation details
- [PLAN.md](docs/PLAN.md) - Future features and roadmap
- [research.md](docs/research.md) - Development research and exploration notes

## Testing

Test files and test cases can be found in the [tests/](tests/) directory:
- [test_bootstrap.py](tests/test_bootstrap.py) - Test bootstrap script
- [test_bootstrap.sh](tests/test_bootstrap.sh) - Shell script for bootstrapping tests
- [test_ofind.py](tests/test_ofind.py) - Test suite for ofind command
- [test_runner.md](tests/test_runner.md) - Test cases documentation

## Examples

The [examples/](examples/) directory contains sample projects for testing:
- [HelloWorld](examples/HelloWorld/) - Simple Xcode project for testing LLDB commands
