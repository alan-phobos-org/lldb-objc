# macOS Sandbox Testing Summary

This document summarizes key learnings about testing macOS sandbox restrictions, derived from building the `osbx` LLDB command and `osbx-standalone` scanner.

## Two Sandbox Mechanisms

macOS uses two distinct sandboxing approaches:

| Mechanism | Used By | How It Works |
|-----------|---------|--------------|
| **App Sandbox (Entitlements)** | App Store apps, signed apps | Kernel enforces based on `com.apple.security.app-sandbox` entitlement; system creates container at `~/Library/Containers/<bundle-id>/` |
| **Launchd Profiles (.sb files)** | System daemons (apsd, rapportd, etc.) | `sandbox_init()` loads SBPL profile at process startup; profiles live in `/System/Library/Sandbox/Profiles/` |

This distinction is critical: you cannot simulate App Sandbox by copying entitlements to an ad-hoc signed binary because the kernel won't create the required container infrastructure.

## Testing Approaches

### For LLDB Debugging Sessions
Use the `osbx` command (in `scripts/objc_sandbox.py`) which evaluates expressions in the target process context. This works well for:
- Quick audits during debugging
- Testing actual process sandbox state
- ~300 paths/second throughput

### For Bulk Scanning
Use `osbx-standalone` (in `tools/osbx-standalone/`) which runs as a native binary at ~50,000+ paths/second. Three approaches:

1. **Custom SBPL Profile** (`--profile`): Best for testing specific sandbox rules
2. **Inherited Entitlements** (`sign-with-entitlements.sh`): Limited utility due to restrictions below
3. **Fork from Sandboxed Process**: Inherits parent's sandbox via LLDB

## Key Limitations Discovered

### Entitlement Restrictions
Many entitlements only work with Apple-signed binaries:
- `com.apple.private.*` - Always restricted
- `com.apple.keystore.*` - Restricted
- `com.apple.rootless.*` - Restricted
- `com.apple.security.app-sandbox` - Requires system container setup

When copying entitlements from system binaries, these must be filtered out or the binary will be killed at launch (SIGKILL, exit code 137).

### System Daemon Profiles
Launchd `.sb` profiles often use parameters like `(param "TMPDIR")` that require runtime values. These profiles cannot be used directly with `sandbox_init()` without modification.

### LLDB Expression Context
When using LLDB to evaluate `sandbox_check()` or `NSFileManager` methods, the code runs in an injected context that may not perfectly reflect the target process's sandbox state. This is especially true for processes using `sandbox_init()` rather than App Sandbox entitlements.

## Practical Recommendations

| Goal | Recommended Approach |
|------|---------------------|
| Audit a running sandboxed app | Use `osbx` LLDB command |
| Test a custom sandbox profile | Use `osbx-standalone --profile custom.sb` |
| Understand system daemon restrictions | Read the `.sb` file in `/System/Library/Sandbox/Profiles/` |
| Bulk scan with specific restrictions | Create simplified SBPL profile, use `osbx-standalone` |

## Tools Provided

```
tools/osbx-standalone/
├── main.c                    # Scanner source (build with `make`)
├── Makefile                  # Builds universal binary
├── sign-with-entitlements.sh # Extract & apply entitlements from target
├── sandbox_profiles/         # Sample SBPL profiles
│   ├── permissive.sb        # Allows most, blocks sensitive paths
│   ├── restrictive.sb       # Minimal access (like system daemons)
│   ├── app-sandbox-default.sb
│   └── app-sandbox-network.sb
└── README.md
```

**Note**: Source distribution is preferred over pre-built binaries because users must sign the binary for their environment anyway.

## References

- [SANDBOX_DESIGN.md](SANDBOX_DESIGN.md) - Full design documentation
- [PITFALLS.md](PITFALLS.md) - Common issues and solutions
- Apple's `sandbox-exec(1)` man page
- `/System/Library/Sandbox/Profiles/*.sb` - System sandbox profiles
