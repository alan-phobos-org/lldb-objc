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

Run the installation script to copy scripts to `~/.lldb-objc/` and configure your `~/.lldbinit`:

```bash
cd /path/to/lldb-objc
./install.py
```

Scripts are installed to `~/.lldb-objc/scripts/` for a stable path. The commands will be available automatically whenever you start LLDB.

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

Install dev dependencies first:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest                            # Unit tests (fast)
./tests/run_all_tests.py          # Integration tests
./tests/run_all_tests.py --quick  # Quick subset only
```

See [tests/test_runner.md](tests/test_runner.md) for more details on the test framework.

## Examples

The [examples/](examples/) directory contains sample projects for testing:
- [HelloWorld](examples/HelloWorld/) - Simple Xcode project for testing LLDB commands

## Configuring the LLM CLI Tool

The `oexplain` command uses Simon Willison's [llm](https://github.com/simonw/llm) command line tool. Here's how to configure it:

### Installing llm

```bash
pip install llm
```

### Setting the Default Model

View the current default model:
```bash
llm models default
```

Set a new default model:
```bash
llm models default gpt-4o
```

### Setting API Keys

For OpenAI:
```bash
llm keys set openai
# Paste your API key when prompted
```

For other providers, use the appropriate key name:
```bash
llm keys set anthropic
llm keys set openrouter
```

Alternatively, set the API key via environment variable:
```bash
export OPENAI_API_KEY="sk-your-key-here"
```

### Configuring an OpenAI-Compatible Endpoint

To use a custom OpenAI-compatible endpoint (e.g., a local proxy or alternative model), create or edit the `extra-openai-models.yaml` file:

```bash
# Find the configuration directory
llm logs path
# The extra-openai-models.yaml file goes in the same directory
```

Add your configuration to `extra-openai-models.yaml`:

```yaml
- model_id: my-proxy-model
  model_name: gpt-4o
  api_base: "http://localhost:8080/v1"
  api_key_name: my-proxy-key
```

Example configuration for `gpt-oss-120b` via a local proxy:

```yaml
- model_id: gpt-oss-120b
  model_name: gpt-oss-120b
  api_base: "http://localhost:8080/v1"
  api_key_name: openai
```

Example configuration for `gpt-oss-120b` via the official OpenAI endpoint:

```yaml
- model_id: gpt-oss-120b
  model_name: gpt-oss-120b
  api_base: "https://api.openai.com/v1"
  api_key_name: openai
```

Configuration options:
- `model_id`: The name you'll use to reference this model in llm
- `model_name`: The model identifier to pass to the API
- `api_base`: The API endpoint URL
- `api_key_name`: Name of the stored API key to use (set with `llm keys set <name>`)

Set the API key for your endpoint:
```bash
llm keys set my-proxy-key
# Paste your API key when prompted
```

Use the configured model:
```bash
llm -m my-proxy-model "your prompt here"
```

Or set it as the default:
```bash
llm models default my-proxy-model
```

Verify your configuration:
```bash
llm models --options -m my-proxy-model
```

For more details, see the [llm documentation](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models).

## oexplain Benchmarks

```log
(lldb) oexplain --claude -a $pc
Sending 54 lines of disassembly to Claude (annotating)...
>> ```asm
>> HelloWorld`main:
>>     0x100000a88 <+0>:   sub    sp, sp, #0x60
>>     0x100000a8c <+4>:   stp    x29, x30, [sp, #0x50]
>>     0x100000a90 <+8>:   add    x29, sp, #0x50
>>     0x100000a94 <+12>:  mov    w8, #0x0                          ; return value = 0
>>     0x100000a98 <+16>:  stur   w8, [x29, #-0x24]
>>     0x100000a9c <+20>:  stur   wzr, [x29, #-0x4]
>>     0x100000aa0 <+24>:  stur   w0, [x29, #-0x8]                   ; save argc
>>     0x100000aa4 <+28>:  stur   x1, [x29, #-0x10]                  ; save argv
>>     0x100000aa8 <+32>:  bl     0x100000b80                        ; @autoreleasepool {
>>     0x100000aac <+36>:  str    x0, [sp, #0x20]                    ; save pool token
>>     0x100000ab0 <+40>:  adrp   x0, 4
>>     0x100000ab4 <+44>:  add    x0, x0, #0x70                      ; @"Starting HelloWorld..."
>>     0x100000ab8 <+48>:  bl     0x100000b5c                        ; NSLog(@"Starting HelloWorld...")
>>     0x100000abc <+52>:  adrp   x8, 8
>>     0x100000ac0 <+56>:  add    x0, x8, #0x148                     ; Greeter class
>>     0x100000ac4 <+60>:  bl     0x100000b68                        ; greeter = [[Greeter alloc] init]
>>     0x100000ac8 <+64>:  ldr    x1, [sp, #0x10]
>>     0x100000acc <+68>:  sub    x8, x29, #0x18
>>     0x100000ad0 <+72>:  str    x8, [sp, #0x18]                    ; &greeter for later cleanup
>>     0x100000ad4 <+76>:  stur   x0, [x29, #-0x18]                  ; store greeter
>>     0x100000ad8 <+80>:  ldur   x0, [x29, #-0x18]                  ; load greeter (self)
>>     0x100000adc <+84>:  adrp   x2, 4
>>     0x100000ae0 <+88>:  add    x2, x2, #0x90                      ; @"World"
>>     0x100000ae4 <+92>:  bl     0x100000bc0                        ; [greeter sayHello:@"World"]
>>     0x100000ae8 <+96>:  ldr    x1, [sp, #0x10]
>>     0x100000aec <+100>: ldur   x0, [x29, #-0x18]                  ; load greeter (self)
>>     0x100000af0 <+104>: adrp   x2, 4
>>     0x100000af4 <+108>: add    x2, x2, #0xb0                      ; @"LLDB"
>>     0x100000af8 <+112>: bl     0x100000bc0                        ; [greeter sayHello:@"LLDB"]
>>     0x100000afc <+116>: ldr    x1, [sp, #0x10]
>>     0x100000b00 <+120>: ldur   x0, [x29, #-0x18]                  ; load greeter (self)
>>     0x100000b04 <+124>: mov    x2, #0x2a                          ; 42
>>     0x100000b08 <+128>: mov    x3, #0x3a                          ; 58
>>     0x100000b0c <+132>: bl     0x100000ba0                        ; result = [greeter add:42 to:58]
>>     0x100000b10 <+136>: stur   x0, [x29, #-0x20]                  ; store result
>>     0x100000b14 <+140>: ldur   x8, [x29, #-0x20]                  ; load result
>>     0x100000b18 <+144>: mov    x9, sp
>>     0x100000b1c <+148>: str    x8, [x9]                           ; push result as variadic arg
>>     0x100000b20 <+152>: adrp   x0, 4
>>     0x100000b24 <+156>: add    x0, x0, #0xd0                      ; @"Sum is: %ld"
>>     0x100000b28 <+160>: bl     0x100000b5c                        ; NSLog(@"Sum is: %ld", result)
>>     0x100000b2c <+164>: adrp   x0, 4
>>     0x100000b30 <+168>: add    x0, x0, #0xf0                      ; @"Done!"
>>     0x100000b34 <+172>: bl     0x100000b5c                        ; NSLog(@"Done!")
>>     0x100000b38 <+176>: ldr    x0, [sp, #0x18]                    ; &greeter
>>     0x100000b3c <+180>: mov    x1, #0x0                           ; nil
>>     0x100000b40 <+184>: bl     0x100000b8c                        ; greeter = nil (release)
>>     0x100000b44 <+188>: ldr    x0, [sp, #0x20]                    ; pool token
>>     0x100000b48 <+192>: bl     0x100000b74                        ; } // drain autoreleasepool
>>     0x100000b4c <+196>: ldur   w0, [x29, #-0x24]                  ; return 0
>>     0x100000b50 <+200>: ldp    x29, x30, [sp, #0x50]
>>     0x100000b54 <+204>: add    sp, sp, #0x60
>>     0x100000b58 <+208>: ret
>> ```

[Claude responded in 19.8s]
(lldb) oexplain --claude $pc
Sending 54 lines of disassembly to Claude (explaining)...
>> Standard Objective-C `main()` with autorelease pool wrapping. Creates a `Greeter` object, calls `sayHello:` twice with `@"World"` and `@"LLDB"`, then `add:to:` with 42 + 58, logs the result, cleans up, returns 0.
>> 
>> **First 5 calls:**
>> 1. `objc_autoreleasePoolPush` — push pool
>> 2. `NSLog(@"Starting HelloWorld...")` — log entry
>> 3. `objc_alloc_init(Greeter)` — create greeter
>> 4. `[greeter sayHello:@"World"]` — first greeting
>> 5. `[greeter sayHello:@"LLDB"]` — second greeting

[Claude responded in 14.2s]
```