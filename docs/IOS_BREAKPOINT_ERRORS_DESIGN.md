# iOS System Binary Breakpoint Errors - Research and Solutions

## Problem Statement

When debugging iOS system binaries with `obrk`, users encounter errors like:

```
warning: failed to set breakpoint site at 0xddq4w34... for breakpoint 1.1: error: 9 sending the breakpoint request
```

Critically, using `b <addr>` with the same address works fine.

This document analyzes the root causes and proposes fixes.

---

## Root Cause Analysis

### Primary Cause: SBAddress vs Raw Address

**The actual bug**: `obrk` was using `BreakpointCreateBySBAddress(SBAddress)` instead of `BreakpointCreateByAddress(uint64_t)`.

The `SBAddress` object returned by `target.ResolveLoadAddress()` contains:
- The load address (correct)
- Section-relative offset and module context (problematic)

For iOS shared cache binaries, this section context can cause issues:
1. The section information doesn't match what debugserver expects
2. The GDB remote protocol packet (`Z0,<address>,<length>`) gets malformed
3. debugserver returns an error

**Using raw load address** (what `b <addr>` does internally) bypasses this issue entirely.

### Error Code Meaning

The "error 9 sending the breakpoint request" is a GDB Remote Protocol error. In the protocol:

- **Error 9 (EBADF)**: Bad file descriptor / invalid resource
- **Error 2 (ENOENT)**: No such file or entry
- **Error 14 (EFAULT)**: Invalid pointer / memory fault

However, **error codes in GDB RSP are not standardized** - their meaning depends on the debugserver implementation.

### 2. Software vs Hardware Breakpoints

LLDB uses **software breakpoints** by default, which work by:

1. Reading the instruction at the target address
2. Replacing it with a trap instruction (`brk` on ARM64)
3. When hit, restoring the original instruction

**On iOS system binaries, this fails because:**

- Code pages are **signed and read-only**
- iOS enforces **code signature verification** at the page level
- Writing a breakpoint instruction **invalidates the entire 16KB page**
- Attempting to execute invalidated code causes `EXC_BAD_ACCESS (code=50)`

### 3. Code Signing Enforcement

iOS uses **CS_ENFORCEMENT** flags on processes. When debugserver tries to write a software breakpoint:

1. The write succeeds (debugserver has task port access)
2. The page's code signature is invalidated
3. On next execution in that page, the kernel terminates the process with "code signing error"

### 4. Platform Binary Requirements

To debug iOS system binaries, debugserver needs special privileges:

| Requirement | Purpose |
|-------------|---------|
| `task_for_pid-allow` | Get task ports of other processes |
| `com.apple.system-task-ports` | Access Apple binary task ports |
| `platform-application` | Execute past sandbox platform profile |
| `run-unsigned-code` | Allow unsigned code execution |
| **Platform binary status** | Access exception ports of platform binaries |

**Key insight**: Even with all entitlements, debugserver must be marked as a **platform binary** (`TF_PLATFORM` flag in task struct) to debug other platform binaries.

### 5. AMFI (Apple Mobile File Integrity)

AMFI enforces code signing and can reject debugserver operations:

- "AMFI: code signature validation failed"
- "Killed: 9" - AMFI terminating the process
- Connection rejections when signature checks fail

---

## The Fix

### Solution: Use Raw Load Address (Implemented)

The fix is simple - use `BreakpointCreateByAddress(uint64_t)` instead of `BreakpointCreateBySBAddress(SBAddress)`:

```python
# Before (broken for iOS shared cache):
breakpoint = target.BreakpointCreateBySBAddress(resolved_addr)

# After (works like `b <addr>`):
load_addr = resolved_addr.GetLoadAddress(target)
breakpoint = target.BreakpointCreateByAddress(load_addr)
```

This matches the behavior of LLDB's `b <addr>` command.

---

## Other Potential Issues (Environment-Specific)

The following issues can also cause breakpoint failures, but are unrelated to the `obrk` bug:

### Solution 1: Use Hardware Breakpoints

If software breakpoints fail due to code signing, ARM64 supports hardware breakpoints:

```
(lldb) breakpoint set -H -a 0x<address>
```

**Limitations:**
- ARM64 typically has only 4-6 hardware breakpoints available
- Some iOS implementations may have fewer

### Solution 2: Modify CS Flags on Target Process (Requires Jailbreak)

Use `csflags` tool to flip the `CS_GET_TASK_ALLOW` (0x4) bit:

```bash
# On device with jailbreak
csflags -c <pid>  # Clear enforcement
```

This allows software breakpoints to work without invalidating the signature.

### Solution 3: Platformize debugserver (Requires Jailbreak + Kernel Access)

Use `platformize` utility to set `TF_PLATFORM` flag:

```bash
platformize <debugserver_pid>
```

This requires kernel task port access, typically only available on jailbroken devices.

### Solution 4: Use Properly Entitled debugserver

Re-sign debugserver with full entitlements:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>com.apple.springboard.debugapplications</key>
    <true/>
    <key>com.apple.system-task-ports</key>
    <true/>
    <key>get-task-allow</key>
    <true/>
    <key>platform-application</key>
    <true/>
    <key>run-unsigned-code</key>
    <true/>
    <key>task_for_pid-allow</key>
    <true/>
</dict>
</plist>
```

Sign with: `ldid -Sentitlements.plist debugserver` or `codesign -s - --entitlements entitlements.plist -f debugserver`

### Solution 5: Use Corellium or Similar Virtualization

For testing purposes, iOS virtualization platforms like Corellium provide full debugging access without the restrictions of physical hardware.

---

## References

- [Make Debugging Great Again](https://newosxbook.com/articles/MDGA.html) - Platform binary requirements
- [LLDB GDB Remote Protocol](https://lldb.llvm.org/resources/lldbgdbremote.html) - Protocol documentation
- [Hardware Breakpoints on ARM64](https://aarzilli.github.io/debugger-bibliography/hwbreak.html) - Technical details
- [Debugging iOS Applications](https://mas.owasp.org/MASTG/techniques/ios/MASTG-TECH-0084/) - OWASP guide
- [debugserver_azj](https://github.com/lich4/debugserver_azj) - Alternative debugserver

---

## Summary

| Cause | Solution | Status |
|-------|----------|--------|
| **SBAddress section context** | Use raw load address | **Fixed** |
| Code signing enforcement | Hardware breakpoints | Environment-specific |
| Missing entitlements | Re-sign debugserver | Environment-specific |
| Not platform binary | platformize tool | Environment-specific |

The primary bug (using `BreakpointCreateBySBAddress` instead of `BreakpointCreateByAddress`) has been fixed in `scripts/objc_breakpoint.py`.
