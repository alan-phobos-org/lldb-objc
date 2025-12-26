# LLDB Objective-C Automation - Feature Roadmap

This document outlines suggested features to enhance LLDB for iOS/macOS security researchers and reverse engineers.

---

## Immediate Next Steps (Fully Designed & Ready to Implement)

These features have complete design specifications and are ready for implementation:

### 1. Wildcard Class Finder (`oclasses`)

**Status:** ✨ Fully Designed - Ready to Implement

**Description:** Find classes matching wildcard patterns to discover private classes and explore frameworks.

**Why it's useful:**
- Essential for discovering private classes when exact names are unknown
- Explore entire frameworks by pattern (e.g., all IDS* classes)
- Foundation for other wildcard features
- Quick discovery of related classes

**Technical approach:**
- Use `objc_copyClassList(unsigned int *outCount)` to get all registered classes
- Use `class_getName(Class cls)` to convert Class pointers to names
- Apply wildcard pattern matching using `matches_pattern()` function
- Sort and display results with counts
- Proper memory management (free allocated arrays)

**Resolution Chain:**
```
1. Allocate count variable: malloc(sizeof(unsigned int))
2. objc_copyClassList() → Get array of Class pointers
3. Read count from allocated variable
4. For each class in array:
   a. class_getName() → Get class name string
   b. matches_pattern() → Filter by wildcard pattern
   c. Store matching class names
5. Sort and display results
6. free() class list array
7. free() count variable
```

**Implementation details:**
- New file: `objc_classes.py`
- Reuse `matches_pattern()` from `objc_find.py`
- Pattern supports: `*` (any chars), `?` (single char)
- Case-insensitive matching
- Warn on large result sets (10,000+ classes possible)

**Estimated complexity:** Low

**Example usage:**
```
oclasses IDS*                    # All classes starting with "IDS"
oclasses *Service                # All classes ending with "Service"
oclasses *Navigation*            # All classes containing "Navigation"
oclasses _UI*                    # All private UIKit classes
```

**Output format:**
```
Searching for classes matching: IDS*

Found 23 classes:
  IDSAccount
  IDSAccountController
  IDSBaseMessage
  IDSConnection
  IDSDevice
  IDSService
  IDSServiceDelegate
  ...

Total: 23 class(es)
```

---

### 2. Wildcard Class Support for `ofind`

**Status:** ✨ Fully Designed - Ready to Implement

**Description:** Extend existing `ofind` command to accept wildcard class names, enabling selector searches across multiple classes simultaneously.

**Why it's useful:**
- Search for methods across related classes in one command
- Discover which classes in a framework implement specific methods
- Powerful for bulk exploration and pattern discovery
- More efficient than running ofind multiple times

**Technical approach:**
- Modify existing `objc_find.py` to detect wildcards in class name
- If wildcards present: expand to list of matching classes using same logic as `oclasses`
- If no wildcards: use existing `NSClassFromString()` behavior (backward compatible)
- Iterate over matched classes, running existing method enumeration logic
- Group results by class with clear separators

**Resolution Chain:**
```
1. Parse command: extract class_pattern and selector_pattern
2. If class_pattern contains wildcards:
   a. Allocate count variable
   b. objc_copyClassList() → Get all classes
   c. Read count
   d. For each class:
      - class_getName() → Get name
      - matches_pattern(name, class_pattern) → Filter
      - Store matching Class pointers
   e. free() class list and count variable
3. Else (no wildcards):
   - NSClassFromString() → Get single class (existing behavior)
4. For each matched class:
   a. class_copyMethodList() → Instance methods
   b. object_getClass() → Metaclass
   c. class_copyMethodList() → Class methods
   d. Filter by selector_pattern
   e. Display results grouped by class
5. Clean up allocated memory
```

**Implementation details:**
- Modify: `objc_find.py` main function
- Add: `get_matching_classes(frame, pattern)` helper
- Reuse: `matches_pattern()` for both class and selector filtering
- Backward compatible: existing commands work unchanged
- Detect wildcards: check for `*` or `?` in class name

**Estimated complexity:** Medium

**Example usage:**
```
# NEW: Wildcard class patterns
ofind IDS* sendMessage           # Find 'sendMessage' in all IDS* classes
ofind *Service delegate          # Find 'delegate' in all *Service classes
ofind NS*Array count             # Find 'count' in NSArray, NSMutableArray, etc.
ofind UI*View* set*              # Find 'set*' selectors in all UI view classes

# Existing usage still works
ofind IDSService sendMessage     # Single class (no wildcards)
```

**Output format:**
```
Searching for selectors in classes: IDS*
Filter pattern: sendMessage

================================================================================
Class: IDSAccount
Instance methods (1):
  -sendMessage:withOptions:

Class: IDSConnection
Instance methods (2):
  -sendMessage:
  -sendMessageWithData:

Class: IDSService
Instance methods (1):
  -sendMessage:toDestinations:

================================================================================
Total: 4 method(s) across 3 class(es)
```

**Technical challenges:**
- Performance: Searching all classes then all methods can be slow
  - Solution: Show progress for large searches, early exit if too many classes
- Output management: Results can be overwhelming
  - Solution: Group by class, clear separators, consider `--summary` flag
- Backward compatibility: Must not break existing usage
  - Solution: Explicit wildcard detection

---

### 3. Objective-C Method Caller (`ocall`)

**Status:** ✨ Fully Designed - Ready to Implement

**Description:** Call Objective-C methods with arguments from the LLDB command line, returning the result.

**Why it's useful:**
- Quickly test private APIs without writing code
- Create new objects and call class methods interactively
- Trigger specific code paths for analysis
- Convenient syntax compared to raw `expr` command
- Useful for proof-of-concept testing

**Technical approach:**
- Parse input format: `-[Class method:arg1]` or `+[Class method:arg1]`
- Remove leading `-` or `+` to get evaluable expression
- Use LLDB's `frame.EvaluateExpression()` to execute Objective-C code
- LLDB's evaluator handles all complex parsing (literals, nested calls, etc.)
- Display result with value, summary, and type information
- Minimal custom parsing - leverage LLDB's built-in capabilities

**Resolution Chain:**
```
1. Parse input: -[Class method:arg1 arg2:arg3]
2. Extract:
   a. Method type (- or +)
   b. Class name
   c. Full selector with arguments
3. Optional validation:
   a. NSClassFromString() → Verify class exists
   b. NSSelectorFromString() → Verify selector exists
4. Construct Objective-C expression:
   Remove leading '-' or '+': [ClassName selector:arg1 arg2:arg2]
5. frame.EvaluateExpression() → Execute and get result
6. Format and display result:
   - GetValue() → Raw value
   - GetSummary() → Human-readable summary
   - GetTypeName() → Type information
```

**Implementation details:**
- New file: `objc_call.py`
- Simple parsing: just validate and strip leading `-/+`
- LLDB evaluator handles Objective-C literals: `@"string"`, `@123`, `@[]`, `@{}`
- Let LLDB handle errors (method not found, wrong args, etc.)
- Display comprehensive result information

**Estimated complexity:** Moderate (simple with LLDB evaluator, complex if custom parsing)

**Example usage:**
```
# Class methods (create new objects)
ocall +[NSDate date]
ocall +[NSString stringWithFormat:@"Value: %d" 42]
ocall +[NSNumber numberWithBool:YES]
ocall +[NSArray arrayWithObjects:@"a" @"b" nil]

# Instance methods (requires object in scope)
ocall -[myString uppercaseString]
ocall -[myArray objectAtIndex:0]
ocall -[myDict valueForKey:@"name"]

# Complex expressions
ocall -[(NSString *)[$r0 description] length]
```

**Output format:**
```
ocall +[NSDate date]

Expression: [NSDate date]
Result: 0x600001234560
Summary: "2025-12-25 10:30:45 +0000"
Type: NSDate *
```

**Technical challenges:**
- **Argument Parsing**: Objective-C literals are complex (`@"string"`, `@[]`, `@{}`)
  - Solution: Don't parse - let LLDB's evaluator handle it (recommended)
- **Instance vs Class Methods**: Instance methods need existing object in scope
  - Solution: Document clearly; `ocall -[obj method]` requires `obj` variable
- **Return Value Display**: Different types display differently
  - Solution: Show GetValue(), GetSummary(), GetTypeName() for complete info
- **Error Handling**: Method doesn't exist, wrong args
  - Solution: Let LLDB's evaluator handle errors, display clearly

**Alternative approach:**
Instead of custom parsing, `ocall` could be a thin wrapper:
1. Validate syntax (starts with `-[` or `+[`)
2. Remove leading `-` or `+`
3. Pass to LLDB's `expr` command
4. Format output nicely

This leverages LLDB's capabilities while providing convenient syntax.

---

## High Priority Features (Original Roadmap)

### 4. Method Implementation Finder (`ofind`)

**Status:** ✅ IMPLEMENTED (Current version searches within a class)

**Description:** Search for selectors within a specific class or across all classes (see wildcard support above).

**Current implementation:**
- Searches for methods within a specified class
- Supports pattern matching for selector filtering
- Lists both instance and class methods

**Note:** The original vision for this command was to search across ALL classes for implementations of a specific selector. With the new wildcard support (Feature #2 above), you can now achieve this with `ofind * selectorName`.

---

### 5. Class Hierarchy Viewer (`oclass`)

**Description:** Display complete class hierarchy, instance variables, properties, and methods for a given class.

**Why it's useful:**
- Essential for understanding private classes and their capabilities
- Reveals instance variables that aren't exposed as properties (common in private APIs)
- Shows inherited methods and properties from superclasses
- Helps identify what data a class stores and what operations it supports
- Critical for reverse engineering when headers aren't available

**Technical approach:**
- Use `NSClassFromString()` to get the class
- Use `class_getSuperclass()` recursively to build hierarchy chain
- Use `class_copyIvarList()` to enumerate instance variables with types
- Use `class_copyPropertyList()` to list properties
- Use `class_copyMethodList()` for both instance and class methods
- Use `class_copyProtocolList()` to show adopted protocols
- Format output similar to `class-dump` but from live runtime
- Use `ivar_getTypeEncoding()` and `method_getTypeEncoding()` to show signatures

**Estimated complexity:** Medium

**Example usage:**
```
oclass UIViewController
oclass _UINavigationBarPrivate
oclass -ivars NSString  # show only ivars
oclass -methods UIView  # show only methods
```

---

### 6. Method Watcher with Argument Logging (`owatch`)

**Description:** Set a breakpoint that automatically logs method arguments and return values without stopping execution.

**Why it's useful:**
- Monitor method calls in real-time without manual inspection
- Track data flow through specific methods during app execution
- Essential for understanding what data is passed to security-critical methods (encryption, authentication, etc.)
- Reduces tedious manual breakpoint inspection
- Can capture hundreds of calls automatically for analysis

**Technical approach:**
- Similar to `obrk` but with automatic breakpoint callback
- Use `target.BreakpointCreateByAddress()` with scripted callback
- In callback, use `frame.EvaluateExpression()` to access `self` and method arguments
- For arguments: use `$arg0` (self), `$arg1` (SEL), `$arg2`, `$arg3`, etc.
- Parse method signature using `method_getTypeEncoding()` to determine argument types
- Format and print arguments based on type (objects, primitives, pointers)
- For return value: use `thread.StepOut()` and capture return register
- Automatically continue execution after logging
- Option to save logs to file

**Estimated complexity:** Complex

**Example usage:**
```
owatch -[NSUserDefaults setObject:forKey:]
owatch -[CommonCrypto CCCrypt::::::::] -save crypto_calls.log
owatch +[NSURLRequest requestWithURL:] -args  # show arguments only
```

---

## Medium Priority Features

### 7. Selector Search (`ogrep`)

**Description:** Search for methods matching a pattern (regex or wildcard) across all classes.

**Note:** This feature significantly overlaps with the wildcard `ofind` enhancement (Feature #2). Consider whether both are needed or if wildcard `ofind` is sufficient.

**Why it's useful:**
- Discover private APIs related to specific functionality (e.g., all methods containing "decrypt")
- Find methods following naming conventions
- Explore what methods are available for a particular feature
- Useful when you know part of a method name but not the exact signature

**Technical approach:**
- Use `objc_getClassList()` to enumerate classes
- Use `class_copyMethodList()` on each class
- Use `sel_getName()` to get method names
- Apply regex or wildcard matching on selector names
- Group results by class or sort alphabetically
- Option to filter by framework/library

**Estimated complexity:** Simple

**Example usage:**
```
ogrep ".*crypto.*"  # find all methods with 'crypto' in name
ogrep -i "password"  # case-insensitive search
ogrep "set.*:" -class NSUserDefaults  # search within specific class
```

**Alternative:** Use `ofind * crypto` (with wildcard class support) to achieve similar results.

---

### 8. Instance Tracker (`oinstances`)

**Description:** Find all live instances of a specific class in memory.

**Why it's useful:**
- Locate objects to inspect their current state
- Essential for understanding app state and data flow
- Helps find singleton instances or global objects
- Useful for memory analysis and leak detection
- Can inspect private objects that aren't easily accessible

**Technical approach:**
- Use `heap` command (if available) or custom implementation
- Alternative: iterate through heap using `malloc_zone_t` functions
- For each allocation, check if it's an Objective-C object using `object_getClass()`
- Compare against target class using `class_isKindOfClass()` or pointer comparison
- Collect addresses of matching instances
- Display with option to print descriptions
- Could integrate with `leaks` command output

**Estimated complexity:** Complex

**Example usage:**
```
oinstances UIViewController
oinstances NSData -describe  # show description of each instance
oinstances _Private* -count  # just count instances matching pattern
```

---

### 9. Method Swizzle Helper (`oswizzle`)

**Description:** Easily swizzle (replace) Objective-C method implementations with logging or custom behavior.

**Why it's useful:**
- Quick runtime method hooking without recompiling
- Insert logging into private methods
- Modify app behavior for testing security controls
- Common reverse engineering technique made easier
- Can chain original implementation for transparent hooks

**Technical approach:**
- Resolve source and destination method using runtime APIs
- Use `class_getMethodImplementation()` to get original IMP
- Use `class_replaceMethod()` or `method_exchangeImplementations()` for swizzling
- For logging hooks, create a wrapper that calls original
- Need to handle method signatures and forwarding properly
- Store original IMPs for potential restoration
- Consider using `class_addMethod()` for adding entirely new methods

**Estimated complexity:** Complex

**Example usage:**
```
oswizzle -[NSURLSession dataTaskWithRequest:] -[MyLogger loggedDataTask:]
oswizzle -[CommonCrypto CCCrypt::::::::] -log -continue  # log and call original
```

---

## Lower Priority / Advanced Features

### 10. Block Inspector (`oblock`)

**Description:** Analyze Objective-C blocks (closures) to show their signature, captured variables, and implementation.

**Why it's useful:**
- Blocks are heavily used in modern Objective-C/Swift code
- Understanding block signatures helps with reverse engineering async code
- Captured variables reveal context and state
- Useful for hooking completion handlers and callbacks

**Technical approach:**
- Parse block structure (`Block_layout` from Block_private.h)
- Extract block invoke function pointer
- Parse block descriptor for signature
- Identify captured variables from block layout
- Use `dladdr()` to identify where block is defined
- Set breakpoints on block invocations

**Estimated complexity:** Complex

**Example usage:**
```
oblock 0x123456789  # inspect block at address
oblock -break 0x123456789  # set breakpoint on block invocation
```

---

### 11. Protocol Inspector (`oprotos`)

**Description:** List all classes conforming to a specific protocol.

**Why it's useful:**
- Find all implementations of a protocol
- Understand design patterns and architecture
- Discover alternative implementations
- Useful for finding plugin architectures

**Technical approach:**
- Use `objc_getProtocol()` to get protocol
- Enumerate all classes with `objc_getClassList()`
- Use `class_conformsToProtocol()` to check conformance
- Display required and optional methods from protocol
- Show which methods each class implements

**Estimated complexity:** Simple

**Example usage:**
```
oprotos NSCoding
oprotos -methods UITableViewDelegate  # show protocol methods
```

---

### 12. Backtrace Enhancer (`obt`)

**Description:** Enhanced backtrace that automatically resolves Objective-C method names and shows arguments.

**Why it's useful:**
- Standard LLDB backtraces often show just addresses for dynamic calls
- Resolving symbols makes stack traces more readable
- Seeing arguments in stack frames helps understand call context
- Essential for understanding complex call chains

**Technical approach:**
- Get current backtrace using `thread.GetFrames()`
- For each frame, attempt to resolve as Objective-C method
- Use `$arg0` (self) and `$arg1` (_cmd) to identify method
- Use `class_getName()` and `sel_getName()` to get readable names
- Format output with indentation and argument values
- Optionally filter to show only Objective-C frames

**Estimated complexity:** Medium

**Example usage:**
```
obt  # enhanced backtrace
obt -args  # include argument values
obt -objc  # only show Objective-C frames
```

---

### 13. NSInvocation Helper (`oinvoke`)

**Description:** Dynamically invoke any Objective-C method on any object with proper argument handling.

**Note:** This feature is largely superseded by Feature #3 (`ocall`). The `ocall` command provides similar functionality with a more convenient syntax and leverages LLDB's built-in expression evaluator.

**Why it's useful:**
- Call methods interactively without writing code
- Test private APIs
- Trigger specific code paths for analysis
- Useful for proof-of-concept exploits

**Technical approach:**
- Parse method signature and arguments from command line
- Use `NSInvocation` or direct `objc_msgSend` calling
- Handle various argument types (objects, primitives, structs)
- Return and display return value
- Handle errors gracefully

**Estimated complexity:** Complex

**Example usage:**
```
oinvoke 0x123456 "stringByAppendingString:" @"test"
oinvoke self "valueForKey:" @"privateProperty"
```

**Alternative:** Use the simpler `ocall` command (Feature #3) for most use cases.

---

## Overall Implementation Priority Recommendation

Based on utility, complexity, and dependencies:

**Phase 1 - Foundation (Quick Wins):**
1. ✅ **`obrk`** - Breakpoint setter (COMPLETE)
2. ✅ **`ofind`** - Selector finder (COMPLETE)
3. ✨ **`oclasses`** - Class finder (NEW - Foundation for wildcards)
4. ✨ **Wildcard `ofind`** - (NEW - Builds on #3, backward compatible enhancement)

**Phase 2 - Core Utilities:**
5. ✨ **`ocall`** - Method caller (NEW - Independent, high utility)
6. **`oclass`** - Class introspection (High value for reverse engineering)
7. **`ogrep`** - Selector search (Consider merging with wildcard ofind or skipping)

**Phase 3 - Advanced Features:**
8. **`owatch`** - Method monitoring (Complex but very useful)
9. **`obt`** - Enhanced backtrace (Quality of life improvement)
10. **`oprotos`** - Protocol finder (Nice addition)

**Phase 4 - Specialized Tools:**
11. **`oinstances`** - Instance finder (Advanced use case)
12. **`oswizzle`** - Method swizzling (Requires careful implementation)
13. **`oblock`** - Block inspector (Specialized)
14. **`oinvoke`** - (Consider skipping in favor of `ocall`)

---

## Additional Considerations

### User Experience
- All commands should have `-h` or `--help` flags
- Consider color output for better readability
- Add `-v` verbose mode for debugging
- Support tab completion where possible
- Consistent error messages

### Performance
- Cache runtime lookups where possible
- Add timeouts for long-running operations
- Allow interruption with Ctrl+C
- Consider pagination for large outputs
- Warn users about expensive operations (e.g., enumerating all classes)
- Progress indicators for long-running searches

### Safety
- Add confirmation prompts for destructive operations (like oswizzle)
- Validate inputs to prevent crashes
- Handle edge cases (nil classes, invalid selectors)
- Document limitations and requirements
- Proper memory management (free allocated arrays from runtime functions)

### Integration
- Commands should work well together (pipe outputs)
- Consider JSON output mode for scripting
- Save/load functionality for common workflows
- Integration with existing LLDB commands
- Reuse helper functions across scripts (e.g., `matches_pattern()`)

### Code Quality
- Follow existing patterns from [objc_breakpoint.py](objc_breakpoint.py) and [objc_find.py](objc_find.py)
- Consistent error handling and validation
- Clear, informative output messages
- Comprehensive docstrings
- Memory management best practices (free allocated runtime arrays)
