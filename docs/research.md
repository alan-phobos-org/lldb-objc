# LLDB Objective-C Debugging Tools - Research Report

*Research Date: December 25, 2025*

## Executive Summary

This document examines existing LLDB frameworks and tools that provide features similar to our `obrk` command for setting breakpoints on Objective-C methods. The research focuses on mature, widely-used tools in the iOS/macOS debugging and security research communities.

---

## 1. Chisel (Facebook/Meta)

**Repository:** https://github.com/facebook/chisel
**Maintainer:** Facebook/Meta (now archived)
**Status:** ⚠️ Archived (no longer actively maintained)

### Overview
Chisel is a collection of LLDB commands to assist in debugging iOS and macOS applications. It was widely used in the iOS development community and set the standard for LLDB Python scripting.

### Key Features

#### Breakpoint-Related Commands
- **`bmessage`** - Set a breakpoint for an Objective-C method
  - Syntax: `bmessage -[ClassName methodName:]`
  - **This is directly comparable to our `obrk` command**
  - Sets symbolic breakpoints using LLDB's built-in Objective-C method resolution

#### View Debugging Commands
- `pviews` - Print view hierarchy
- `pvc` - Print view controller hierarchy
- `visualize` - Open images/layers in Preview.app
- `show`/`hide` - Show/hide views
- `mask`/`unmask` - Overlay colored masks on views
- `border`/`unborder` - Add borders to views

#### Object Inspection
- `pclass` - Print class hierarchy
- `pmethods` - Print methods of a class
- `pivar` - Print instance variables
- `presponder` - Print responder chain

#### Memory & Runtime
- `findinstances` - Find instances of a class in memory
- `pblock` - Print block implementation details
- `dcomponents` - Print key UIKit/AppKit components

### Comparison to Our Implementation

| Feature | Chisel `bmessage` | Our `obrk` |
|---------|------------------|-----------|
| Syntax | `-[Class method:]` | `-[Class method:]` |
| Resolution Method | LLDB symbolic breakpoints | Runtime function calls (NSClassFromString, etc.) |
| Private Class Support | ❌ Limited - relies on symbol tables | ✅ Yes - runtime resolution |
| Private Method Support | ❌ Limited | ✅ Yes - runtime resolution |
| Class Methods | ✅ Yes | ✅ Yes |
| Instance Methods | ✅ Yes | ✅ Yes |

### Key Differences

**Chisel's Approach:**
- Uses LLDB's built-in `breakpoint set -n` with Objective-C method names
- Relies on symbols being available in the binary
- Faster for public APIs (no runtime evaluation needed)
- Fails for private/undocumented classes and methods

**Our Approach:**
- Uses runtime functions (`NSClassFromString`, `class_getMethodImplementation`)
- Works with private/undocumented classes and methods
- Requires process to be running (can't set breakpoints before launch)
- More flexible for security research and reverse engineering

### Maintenance Status
⚠️ **Archived in 2023** - Facebook archived this repository, meaning no new features or bug fixes. However, it still works with current LLDB versions for most use cases.

### Verdict
**What Chisel Does Better:**
- Comprehensive view debugging tools (we don't have these)
- Extensive object inspection utilities
- Well-documented and battle-tested
- Large community knowledge base

**What We Do Better:**
- Private class/method support via runtime resolution
- More suitable for reverse engineering scenarios

---

## 2. LLDB Scripts by Derek Selander

**Repository:** https://github.com/DerekSelander/LLDB
**Maintainer:** Derek Selander (active iOS/macOS security researcher)
**Status:** ✅ Actively maintained

### Overview
A comprehensive collection of LLDB commands focused on iOS/macOS reverse engineering, debugging, and security research. Derek Selander is a well-known figure in the iOS security community and author of "Advanced Apple Debugging & Reverse Engineering."

### Key Features

#### Breakpoint & Method Resolution
- **`lookup`** - Search for methods/functions across all loaded modules
  - Can find Objective-C methods, Swift methods, C functions
  - Supports regex patterns
  - Shows module, class, and method information

- **`search`** - Search for classes and methods by name
  - More focused than `lookup`, specifically for class/method discovery

- **`methods`** - Dump all methods for a class (including private)
  - Runtime-based enumeration
  - Shows method signatures

#### Module & Symbol Inspection
- **`dclass`** - Dump complete class information
  - Properties, methods, protocols, instance variables
  - Includes inheritance hierarchy

- **`msl`** - Module symbol lookup
  - Find symbols across loaded frameworks

- **`bimp`** - Breakpoint on implementation address
  - Similar to our approach of breaking on IMP addresses
  - Can be used after resolving a method's implementation

#### Memory & Assembly
- **`grep`** - Search memory for byte patterns
- **`disassemble`** - Enhanced disassembly with symbol resolution
- **`stepout`** - Step out of current function (convenience)

#### iOS/macOS Specific
- **`pclass`** - Print NSObject-derived class info
- **`pprotocol`** - Dump protocol information
- **`pblock`** - Print block internals
- **`sbt`** - Symbolicated backtrace with color coding

### Comparison to Our Implementation

**Overlapping Features:**
- Runtime-based method resolution (similar philosophy to ours)
- Support for private classes/methods
- Focus on reverse engineering use cases

**Different Approach:**
- More focused on *discovery* than breakpoint setting
- Provides broader toolset (not just breakpoints)
- Integrates well with reverse engineering workflow

### Workflow Example
With Derek's scripts, you might:
1. Use `lookup` or `search` to find a private method
2. Use `methods` to see all methods in a class
3. Manually set breakpoint with standard LLDB commands
4. Use `bimp` if you know the implementation address

With our `obrk`:
1. Directly set breakpoint: `obrk -[PrivateClass privateMethod:]`

### Maintenance Status
✅ **Actively Maintained** - Regular updates, works with latest Xcode/LLDB versions

### Verdict
**What Derek's Scripts Do Better:**
- Discovery and exploration (finding what's available)
- Comprehensive reverse engineering toolkit
- Deep inspection of runtime structures
- Active maintenance and community

**What We Do Better:**
- One-command breakpoint setting for Objective-C methods
- More streamlined for the specific use case of "I know the method, just break on it"

---

## 3. LLDB-Scripts (Multiple Contributors)

**Repository:** Various repositories under the `lldb-scripts` topic on GitHub
**Status:** Mixed (some active, some abandoned)

### Notable Projects

#### 3.1 lldb_utils
- Collection of utility functions for LLDB Python scripting
- Helper functions for SBValue inspection, memory reading, etc.
- More of a library than user-facing commands

#### 3.2 lldb-helpers
- Various convenience commands for debugging
- Less focused on Objective-C specifically
- More general C/C++ debugging utilities

#### 3.3 voltron
**Repository:** https://github.com/snare/voltron
**Status:** ⚠️ Maintenance mode

- **Multi-debugger UI** - Works with LLDB, GDB, VDB, WinDbg
- Provides visual debugging interface with separate terminal panes for:
  - Disassembly view
  - Register view
  - Stack view
  - Backtrace view

**Relevance to Our Work:**
- Not directly related to Objective-C breakpoint setting
- More about debugging UX than runtime resolution
- Could be used *alongside* our tools

---

## 4. Frida (Dynamic Instrumentation Framework)

**Repository:** https://github.com/frida/frida
**Maintainer:** Ole André V. Ravnås and community
**Status:** ✅ Very actively maintained

### Overview
While not strictly an LLDB tool, Frida is extremely popular in iOS/macOS security research and provides overlapping functionality.

### Key Features

#### Objective-C Method Hooking
```javascript
// Frida JavaScript API
var hook = ObjC.classes.NSString['- length'].implementation = function() {
    console.log("NSString length called");
    return this.length();
};
```

#### Runtime Method Resolution
- `ObjC.classes` - Access to all Objective-C classes (including private)
- `ObjC.choose()` - Find live instances of a class
- Method hooking/interception (more than just breakpoints)

### Comparison to LLDB Approach

| Feature | Frida | LLDB (Our Tool) |
|---------|-------|-----------------|
| Private Class Access | ✅ Yes | ✅ Yes |
| Runtime Resolution | ✅ Yes | ✅ Yes |
| Breakpoints | ❌ No (uses hooks) | ✅ Yes |
| Code Injection | ✅ Yes | ❌ Limited |
| Script Language | JavaScript | Python |
| Learning Curve | Moderate | Lower (if familiar with LLDB) |
| Performance | Some overhead | Native debugger |
| Use Case | Dynamic analysis, hooking | Traditional debugging |

### Verdict
**Different Tool Category:**
- Frida is for dynamic instrumentation, not debugging
- Can do much more than breakpoints (modify behavior at runtime)
- Steeper learning curve
- Not a replacement for LLDB, but complementary

**When to Use Frida vs LLDB:**
- **Frida:** When you want to modify behavior, trace calls, inject code
- **LLDB:** When you want traditional debugging (step through, inspect state)

---

## 5. Other Notable Tools

### 5.1 class-dump / class-dump-z
**Purpose:** Extract class declarations from Objective-C binaries
**Relevance:** Discovery phase - find classes/methods before debugging
**Status:** Multiple forks, semi-maintained

### 5.2 Hopper / IDA Pro / Ghidra (Disassemblers)
**Purpose:** Static analysis of binaries
**Relevance:** Discover methods/classes offline, then use LLDB for dynamic analysis
**Not LLDB tools:** Separate category

### 5.3 lldb-eval
**Repository:** https://github.com/google/lldb-eval
**Maintainer:** Google
**Purpose:** Fast expression evaluation in LLDB
**Relevance:** Could potentially speed up our runtime evaluations
**Status:** Experimental

---

## Feature Matrix Comparison

| Feature | Our `obrk` | Chisel | Derek's LLDB | Frida |
|---------|-----------|--------|--------------|-------|
| **Breakpoint Setting** |
| Objective-C methods | ✅ | ✅ | ⚠️ Manual | ❌ |
| Private classes | ✅ | ❌ | ✅ (via discovery) | ✅ |
| One-command syntax | ✅ | ✅ | ❌ | ❌ |
| Runtime resolution | ✅ | ❌ | ✅ | ✅ |
| **Discovery Tools** |
| Find methods | ❌ | ⚠️ Some | ✅ Excellent | ✅ |
| Class inspection | ❌ | ✅ | ✅ Excellent | ✅ |
| Module search | ❌ | ❌ | ✅ | ✅ |
| **Other Features** |
| View debugging | ❌ | ✅ Excellent | ❌ | ⚠️ Some |
| Memory inspection | ❌ | ⚠️ Basic | ✅ | ✅ |
| Code injection | ❌ | ❌ | ❌ | ✅ Excellent |
| **Maintenance** |
| Active development | ✅ (ours) | ❌ | ✅ | ✅ |
| Community support | ❌ (new) | ✅ Large | ⚠️ Medium | ✅ Large |

---

## Recommendations

### Should We Continue Building Our Own Tools?

**YES - Continue Development**, but with strategic integration. Here's why:

### Reasons to Continue

1. **Unique Value Proposition**
   - Our `obrk` command fills a specific gap: **one-command breakpoint setting on private Objective-C methods**
   - Chisel's `bmessage` doesn't work for private symbols
   - Derek's scripts require multiple steps (discover, then manually break)
   - Neither provides the exact workflow we want

2. **Learning & Control**
   - Building our own tools provides deep understanding of LLDB Python API
   - Full control over features and behavior
   - Can optimize for our specific use cases

3. **Modern Maintenance**
   - Chisel is archived (2023)
   - Our tool can stay current with latest LLDB features
   - Can add Swift support in the future

### Recommended Strategy: Hybrid Approach

**Build a comprehensive toolkit that includes:**

1. **Keep and Enhance `obrk`**
   - Add error handling improvements
   - Add Swift method support
   - Add category method support
   - Add wildcard/pattern matching

2. **Integrate Discovery Features from Derek's Approach**
   - Add `lookup` command to find methods
   - Add `methods` command to inspect classes
   - Add `search` command for class discovery

3. **Consider Borrowing Ideas from Chisel**
   - View debugging commands (if doing UI work)
   - Object inspection utilities
   - Convenience commands

4. **Create a Cohesive Suite**
   ```
   obrk/        # Our package
   ├── breakpoints.py   # obrk command (what we built)
   ├── discovery.py     # lookup, search, methods (Derek-inspired)
   ├── inspection.py    # pclass, pmethods, pivar (Chisel-inspired)
   └── __init__.py      # Package initialization
   ```

### Immediate Next Steps

1. **Short Term (Complete Current Tool)**
   - Fix the debug issues with `obrk`
   - Add comprehensive error handling
   - Write tests for various scenarios
   - Document edge cases

2. **Medium Term (Expand Features)**
   - Add Swift method support
   - Add method pattern matching
   - Add command to list all breakpoints set by our tool
   - Integration with LLDB's breakpoint naming system

3. **Long Term (Build Suite)**
   - Add discovery commands (inspired by Derek's scripts)
   - Add inspection commands (inspired by Chisel)
   - Create unified documentation
   - Build example workflows for common tasks

### What NOT to Do

1. **Don't try to replace Frida**
   - Different use case (instrumentation vs debugging)
   - Frida is mature and excellent at what it does
   - Use Frida when you need instrumentation, LLDB for debugging

2. **Don't duplicate everything from Chisel/Derek**
   - Focus on our unique value (runtime breakpoints)
   - Only add features that enhance this core capability
   - Reference other tools for features we don't provide

3. **Don't ignore the community**
   - Study how Chisel and Derek structure their code
   - Learn from their API design choices
   - Contribute back if we improve on their ideas

---

## Conclusion

**The landscape of LLDB Objective-C debugging tools is mature but has gaps:**

- **Chisel** was excellent but is now archived and doesn't handle private symbols well
- **Derek's scripts** are comprehensive for discovery but lack streamlined breakpoint setting
- **Frida** is powerful but serves a different purpose (instrumentation)

**Our `obrk` command fills a real gap** in the ecosystem by providing:
- One-command breakpoint setting
- Runtime resolution for private classes/methods
- Active maintenance (under our control)
- Modern, clean implementation

**Recommendation: Continue building, but think bigger.** Create a small, focused suite of LLDB commands that work together to support the iOS/macOS reverse engineering and debugging workflow. Start with `obrk` (breakpoints), then add discovery and inspection tools inspired by the best features of existing frameworks.

The goal should be: **"The modern LLDB toolkit for Objective-C/Swift debugging that Chisel would have evolved into if it were still maintained."**

---

## References & Resources

1. **Chisel (Facebook/Meta)**
   - Repository: https://github.com/facebook/chisel
   - Documentation: README in repository
   - Status: Archived (2023)

2. **Derek Selander's LLDB Scripts**
   - Repository: https://github.com/DerekSelander/LLDB
   - Book: "Advanced Apple Debugging & Reverse Engineering"
   - Status: Actively maintained

3. **Frida**
   - Repository: https://github.com/frida/frida
   - Documentation: https://frida.re/docs/
   - Status: Very active

4. **LLDB Python API Documentation**
   - Official Docs: https://lldb.llvm.org/use/python-reference.html
   - SBDebugger API: Core API for scripting

5. **Objective-C Runtime Documentation**
   - Apple's Official: https://developer.apple.com/documentation/objectivec
   - Runtime functions we use: NSClassFromString, NSSelectorFromString, class_getMethodImplementation

---

*End of Research Report*
