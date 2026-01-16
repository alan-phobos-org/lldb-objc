# iOS System Binary Breakpoint Errors - Research and Solutions

## Problem Statement

When debugging iOS system binaries with `obrk`, users encounter errors like:

```
warning: failed to set breakpoint site at 0xddq4w34... for breakpoint 1.1: error: 9 sending the breakpoint request
```

This document analyzes the root causes and proposes fixes.

---

## Root Cause Analysis

### 1. Error Code Meaning

The "error 9 sending the breakpoint request" is a GDB Remote Protocol error. In the protocol:

- **Error 9 (EBADF)**: Bad file descriptor / invalid resource
- **Error 2 (ENOENT)**: No such file or entry
- **Error 14 (EFAULT)**: Invalid pointer / memory fault

However, **error codes in GDB RSP are not standardized** - their meaning depends on the debugserver implementation. The actual cause is typically one of the following.

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

## Proposed Solutions

### Solution 1: Use Hardware Breakpoints (Immediate)

ARM64 supports hardware breakpoints that don't modify code:

```
(lldb) breakpoint set -H -a 0x<address>
```

Or in Python:
```python
# Instead of BreakpointCreateBySBAddress, use hardware breakpoint
bp = target.BreakpointCreateByAddress(addr)
bp.SetHardware(True)
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

## Implementation Changes for lldb-objc

### Option A: Automatic Hardware Breakpoint Fallback

Modify `objc_breakpoint.py` to detect iOS system binaries and use hardware breakpoints:

```python
def breakpoint_on_objc_method(debugger, command, result, internal_dict):
    # ... existing resolution code ...

    # Detect if target is a system binary
    is_system_binary = is_ios_system_binary(target, resolved_addr)

    if is_system_binary:
        # Use hardware breakpoint
        breakpoint = target.BreakpointCreateByAddress(
            resolved_addr.GetLoadAddress(target)
        )
        if breakpoint.IsValid():
            breakpoint.SetHardware(True)
            if not breakpoint.IsHardware():
                result.SetError(
                    "Failed to set hardware breakpoint. "
                    "Hardware breakpoints required for system binaries. "
                    "Check hardware breakpoint availability with 'watchpoint list'."
                )
                return
    else:
        breakpoint = target.BreakpointCreateBySBAddress(resolved_addr)
```

### Option B: User Warning and Documentation

Add detection and warning when setting breakpoints on system binaries:

```python
def check_system_binary_warning(target, address):
    """Warn user about system binary breakpoint limitations."""
    module = address.GetModule()
    if module.IsValid():
        path = module.GetFileSpec().GetDirectory()
        if path and ("/System/" in path or "/usr/lib/" in path):
            return (
                "WARNING: Setting breakpoint on system binary. "
                "Software breakpoints may fail with 'error 9'. "
                "Consider using hardware breakpoint: breakpoint set -H -a <addr>"
            )
    return None
```

### Option C: PAC-Aware Address Resolution

For arm64e binaries with Pointer Authentication:

```python
def strip_pac(address):
    """Strip PAC bits from authenticated pointer."""
    # Top bits contain PAC, keep lower 48 bits for canonical address
    return address & 0x0000FFFFFFFFFFFF
```

---

## Diagnostic Commands

Add these to help users diagnose the issue:

```
# Check hardware breakpoint availability
(lldb) watchpoint list

# Check if process is platform binary
(lldb) process status
(lldb) image list -h  # Check code signing info

# View debugserver entitlements
(lldb) shell cat /proc/<debugserver_pid>/status

# Check CS flags (on device)
(lldb) shell csops <pid> -status
```

---

## Error Message Improvements

Current error:
```
error: 9 sending the breakpoint request
```

Proposed improved error:
```
error: Failed to set breakpoint at 0x... (error 9: memory write denied)

This typically occurs when debugging iOS system binaries because:
1. Code pages are signed and read-only
2. Software breakpoints require modifying code memory

Solutions:
- Use hardware breakpoint: (lldb) breakpoint set -H -a 0x...
- Ensure debugserver has proper entitlements
- On jailbroken device: use csflags to relax code signing

See: docs/IOS_BREAKPOINT_ERRORS_DESIGN.md
```

---

## References

- [Make Debugging Great Again](https://newosxbook.com/articles/MDGA.html) - Platform binary requirements
- [LLDB GDB Remote Protocol](https://lldb.llvm.org/resources/lldbgdbremote.html) - Protocol documentation
- [Hardware Breakpoints on ARM64](https://aarzilli.github.io/debugger-bibliography/hwbreak.html) - Technical details
- [Debugging iOS Applications](https://mas.owasp.org/MASTG/techniques/ios/MASTG-TECH-0084/) - OWASP guide
- [debugserver_azj](https://github.com/lich4/debugserver_azj) - Alternative debugserver

---

## Summary

| Cause | Solution | Requirements |
|-------|----------|--------------|
| Code signing enforcement | Hardware breakpoints | None |
| Missing entitlements | Re-sign debugserver | Device access |
| Not platform binary | platformize tool | Jailbreak + kernel access |
| CS_ENFORCEMENT flags | csflags tool | Jailbreak |
| PAC/arm64e issues | Strip PAC bits | None |

The recommended approach for most users is **Solution 1: Hardware Breakpoints**, as it requires no special device access and works within iOS's security model.
