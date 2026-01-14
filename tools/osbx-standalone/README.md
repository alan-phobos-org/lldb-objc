# osbx-standalone

A standalone native macOS binary for scanning sandbox filesystem access without LLDB overhead.

## Overview

While the `osbx` LLDB command is convenient for quick audits during debugging sessions, it has inherent overhead from expression evaluation (~300 paths/sec). This standalone tool can scan **50,000+ paths/sec** by running as a native binary.

## Three Approaches

### Option A: Apply Custom Sandbox Profile

Load an SBPL (Sandbox Profile Language) file at runtime using `sandbox_init()`:

```bash
# Build
make

# Run with default restrictive profile
./osbx-standalone

# Run with custom profile
./osbx-standalone --profile sandbox_profiles/app-sandbox-default.sb

# Test sandbox policy only (no filesystem access)
./osbx-standalone --sandbox-only --json
```

### Option B: Match Target App's Entitlements

Extract entitlements from a target app or system binary and sign osbx-standalone with them:

```bash
# Sign with a third-party app's entitlements
./sign-with-entitlements.sh /Applications/SomeApp.app

# Sign with a system daemon's entitlements
./sign-with-entitlements.sh /System/Library/PrivateFrameworks/ApplePushService.framework/apsd

# Now run without applying sandbox (kernel uses entitlements)
./osbx-standalone --no-sandbox /tmp /var ~/Documents
```

For distribution, specify a Developer ID:
```bash
./sign-with-entitlements.sh /Applications/MyApp.app "Developer ID Application: My Name"
```

**Important limitations:**

- **App Sandbox entitlement**: The `com.apple.security.app-sandbox` entitlement requires system container setup and doesn't work with ad-hoc signed binaries. The script automatically filters it out.

- **System daemons**: Binaries like `apsd`, `rapportd`, etc. typically use launchd sandbox profiles (`.sb` files) rather than entitlements. Use Option A with their profile instead:
  ```bash
  # System profiles are in /System/Library/Sandbox/Profiles/
  ls /System/Library/Sandbox/Profiles/*.sb
  ```

- **Restricted entitlements**: Many `com.apple.private.*` and other entitlements only work with Apple-signed binaries. The script automatically filters these out.

### Option C: Fork from Sandboxed Process (via LLDB)

Spawn the scanner as a child of a sandboxed process to inherit its sandbox:

```bash
# In LLDB, after attaching to a sandboxed app:
(lldb) command script import /path/to/osbx_spawn.py
(lldb) osbx-spawn --json
```

The child process inherits the parent's sandbox restrictions, combining LLDB's context with native execution speed.

## Usage

```
osbx-standalone [options] [paths...]

Options:
  --profile FILE     Load sandbox profile from FILE (SBPL format)
  --sandbox-only     Use sandbox_check() instead of access()
  --json             Output results in JSON format
  --quiet            Only output writable paths
  --paths-from FILE  Read paths to test from FILE (one per line)
  --no-sandbox       Skip applying sandbox profile
  --help             Show help message

Examples:
  ./osbx-standalone                           # Default restrictive sandbox
  ./osbx-standalone --profile app.sb          # Custom profile
  ./osbx-standalone --sandbox-only --json     # Policy check only
  ./osbx-standalone /tmp /var ~/Documents     # Scan specific paths
  ./osbx-standalone --paths-from paths.txt    # Paths from file
```

## Sandbox Profiles

Sample profiles are included in `sandbox_profiles/`:

| Profile | Description |
|---------|-------------|
| `app-sandbox-default.sb` | Mimics standard App Store sandbox |
| `app-sandbox-network.sb` | App sandbox with network access |
| `restrictive.sb` | Highly restrictive (minimal access) |
| `permissive.sb` | Permissive (blocks only sensitive paths) |

## Output Formats

### Human-readable (default)

```
WRITABLE: /tmp (directory)
WRITABLE: /private/tmp (directory)
DENIED:   /System (directory)
DENIED:   /usr (directory)
WRITABLE: /dev/null (device)

Total: 3/5 paths writable
```

### JSON (`--json`)

```json
{
  "sandbox_applied": true,
  "check_method": "access",
  "paths_tested": 5,
  "writable_paths": [
    {"path": "/tmp", "type": "directory"},
    {"path": "/private/tmp", "type": "directory"},
    {"path": "/dev/null", "type": "device"}
  ],
  "writable_count": 3
}
```

## Performance

| Approach | Paths/sec | Use Case |
|----------|-----------|----------|
| LLDB `osbx` command | ~300 | Quick audits |
| This tool | ~50,000+ | Deep scans, CI |

## Building

```bash
make            # Build universal binary (arm64 + x86_64)
make sign       # Ad-hoc sign for local testing
make install    # Install to /usr/local/bin
make test       # Run basic tests
```

## Requirements

- macOS 11.0 or later
- Xcode Command Line Tools (for building)
- Code signing identity (for distribution)

## How It Works

1. **Option A** uses `sandbox_init()` to apply an SBPL profile before scanning
2. **Option B** relies on the kernel applying sandbox rules based on code signature entitlements
3. **Option C** inherits sandbox from parent process via `fork()`

The tool uses either:
- `access(path, W_OK)` - Tests actual writability (POSIX + sandbox + ACLs)
- `sandbox_check()` - Tests sandbox policy only (private API, no fs access)

## Limitations

- **macOS only**: `sandbox_init()` is not available on iOS
- **Signing required**: Modern macOS requires signed binaries
- **Profile matching**: Need to extract/recreate target app's sandbox profile
- **Not in-process**: Cannot access target app's memory or state
- **App Sandbox via entitlements**: The `com.apple.security.app-sandbox` entitlement requires system container setup that doesn't work with ad-hoc signing. For sandboxed apps, use Option A with a custom profile instead.
- **System daemon profiles**: Launchd sandbox profiles (`.sb` files) often use parameters like `(param "TMPDIR")` that require runtime values. These may need to be simplified or parameterized for use with this tool.
- **Restricted entitlements**: Many Apple entitlements (`com.apple.private.*`, etc.) only work with Apple-signed binaries and are automatically filtered out.

## Related

- `scripts/objc_sandbox.py` - LLDB `osbx` command implementation
- `docs/SANDBOX_DESIGN.md` - Full design documentation
