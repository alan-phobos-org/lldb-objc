# osbx - Sandbox Filesystem Access Scanner

Design document for `osbx`, an LLDB command that efficiently scans the filesystem to determine which paths are writable from within the currently debugged process's sandbox.

**Related docs:**
- [DESIGN.md](DESIGN.md) - Core architecture
- [PERFORMANCE.md](PERFORMANCE.md) - Performance optimization patterns

---

## Problem Statement

When debugging sandboxed iOS/macOS applications, developers and security researchers need to understand:

1. What filesystem paths the process can actually write to
2. Whether sandbox restrictions are functioning as expected
3. Which paths might be exploitable for sandbox escapes
4. How the sandbox profile differs from expected behavior

Currently, this requires manual testing or external tools that don't integrate with the debugging workflow.

### Use Cases

1. **Security Research**: Audit sandbox profiles for overly permissive rules
2. **App Development**: Verify sandbox entitlements are correctly configured
3. **Reverse Engineering**: Understand what data an app can persist
4. **CTF/Pentesting**: Identify writable paths for privilege escalation

---

## Prior Art & Existing Tools

### Apple's `sbtool` (Private)
- Command: `sbtool <pid> file /path`
- Checks if a specific path is accessible
- Also supports: `sbtool <pid> mach` (Mach ports), `sbtool <pid> inspect` (profile explanation), `sbtool <pid> all`
- **Limitation**: Requires root, checks single paths, not available on iOS

### sb_validator (Open Source)
- URL: https://github.com/Karmaz95/sb_validator
- Command-line utility that validates sandbox operations via `sandbox_check()` kernel API
- Supports multiple filter types (PATH, GLOBAL_NAME, APPLEEVENT_DESTINATION, etc.)
- **Limitation**: Requires manual path specification, no bulk enumeration

### Objection (Frida-based)
- URL: https://github.com/sensepost/objection
- Commands: `env`, filesystem browsing
- **Limitation**: Requires Frida injection, doesn't enumerate writable paths

### `sandbox-exec` (macOS only)
- URL: https://igorstechnoclub.com/sandbox-exec/
- Runs processes under custom sandbox profiles
- **Limitation**: For launching processes, not inspecting running ones

### `asctl sandbox check` (macOS)
- Checks if a process is sandboxed
- **Limitation**: Boolean check only, no path enumeration

### Manual `isWritableFileAtPath:` Testing
- Standard NSFileManager method
- **Limitation**: Tests one path at a time, no discovery

### Key Gap
**No existing tool efficiently enumerates writable paths from within a running debugged process.** The `osbx` command fills this gap by leveraging LLDB's process introspection capabilities.

---

## Design Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         osbx Command                             │
│  osbx [--verbose] [--quick] [--output file] [path_prefix]       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                    Path Enumeration Strategy                     │
│  1. Generate candidate paths (hierarchy or known-paths list)    │
│  2. Filter by existence (batch stat() calls)                    │
│  3. Test writability (batch access(W_OK) or sandbox_check)      │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                      LLDB Expression Evaluation                  │
│  - Batched NSFileManager calls                                  │
│  - Direct syscall access() for minimal overhead                 │
│  - Optional sandbox_check() for pre-flight testing              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### Decision 1: Writability Testing Method

#### Option A: NSFileManager `isWritableFileAtPath:` (Recommended)

```objective-c
[[NSFileManager defaultManager] isWritableFileAtPath:@"/path"]
```

**Pros:**
- High-level API, handles all edge cases
- Accounts for sandbox + POSIX permissions + ACLs
- Available on both iOS and macOS
- Well-tested, production-quality

**Cons:**
- Slightly higher overhead than raw syscall
- May trigger sandbox violation logging

#### Option B: Direct `access(path, W_OK)` Syscall

```c
access("/path", W_OK) == 0
```

**Pros:**
- Minimal overhead
- Direct kernel interaction
- No Objective-C runtime involvement

**Cons:**
- May not account for all macOS security layers
- Doesn't test actual write capability (only permission bits)
- May miss sandbox restrictions in some cases

#### Option C: `sandbox_check()` Private API

```c
// Function signature (from libsystem_sandbox.dylib):
int sandbox_check(pid_t pid, const char *operation, enum sandbox_filter_type type, ...);

// Filter types:
enum sandbox_filter_type {
    SANDBOX_FILTER_NONE = 0,
    SANDBOX_FILTER_PATH = 1,
    SANDBOX_FILTER_GLOBAL_NAME = 2,      // Mach service names
    SANDBOX_FILTER_LOCAL_NAME = 3,
    SANDBOX_FILTER_APPLEEVENT_DESTINATION = 4,
    SANDBOX_FILTER_RIGHT_NAME = 5,
    SANDBOX_FILTER_POSIX_IPC_NAME = 17,
    SANDBOX_FILTER_NVRAM_VARIABLE = 15,
};

// Usage example:
sandbox_check(getpid(), "file-write-data", SANDBOX_FILTER_PATH, path)

// Suppress sandbox violation logging:
sandbox_check(getpid(), "file-write-data",
              SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT, path)
```

**Key operations for file access:**
- `file-read-data` - Read file contents
- `file-write-data` - Write file contents
- `file-read-metadata` - Read file attributes
- `file-write-create` - Create new files
- `file-write-unlink` - Delete files

**Pros:**
- Tests sandbox policy directly without side effects
- No actual filesystem access attempted
- Can use `SANDBOX_CHECK_NO_REPORT` flag to suppress violation logs
- Returns 0 if allowed, non-zero if denied

**Cons:**
- Private API, may change between OS versions
- Only tests sandbox, not POSIX permissions or ACLs
- `SANDBOX_CHECK_NO_REPORT` is a weak import (may not exist on all versions)
- Requires dynamic lookup via `dlsym()` or expression evaluation

#### Recommendation

**Use Option A (NSFileManager) as primary method** with Option C (sandbox_check) as an optional `--sandbox-only` mode for security research. Option A is the most reliable for real-world writability testing.

---

### Decision 2: Path Enumeration Strategy

#### Option A: Full Recursive Enumeration

Enumerate all files starting from root (`/`).

**Pros:**
- Complete coverage
- Discovers unexpected writable paths

**Cons:**
- Extremely slow (100K+ paths on typical system)
- Many paths will be inaccessible anyway
- Could take minutes or crash on large filesystems

#### Option B: Known Interesting Paths (Recommended)

Pre-defined list of security-relevant directories:

```python
INTERESTING_PATHS = [
    # Sandbox container paths (resolved at runtime)
    "{{CONTAINER}}/Documents",
    "{{CONTAINER}}/Library",
    "{{CONTAINER}}/tmp",

    # System temp directories
    "/tmp",
    "/var/tmp",
    "/private/tmp",
    "/private/var/tmp",

    # User directories (macOS)
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
    "~/Library/Caches",

    # iOS-specific
    "/var/mobile/Containers/Shared",
    "/var/mobile/Library/Caches",

    # World-writable system paths
    "/var/folders",
    "/dev/null",
    "/dev/zero",

    # Common sandbox escape targets
    "/private/var/db",
    "/private/var/log",
    "/Library/Application Support",
    "/usr/local",
]
```

**Pros:**
- Fast (100-200 paths vs 100K+)
- Focuses on security-relevant locations
- Predictable execution time

**Cons:**
- May miss unexpected writable paths
- Requires maintenance as OS evolves

#### Option C: Hybrid Approach (Recommended for `--thorough` mode)

1. Start with known interesting paths (Option B)
2. For each writable directory found, enumerate one level deep
3. Stop at configurable depth

**Pros:**
- Discovers writable paths near known locations
- Bounded execution time
- Good balance of coverage and speed

**Cons:**
- More complex implementation
- Still may miss isolated writable paths

#### Recommendation

**Default: Option B (Known Paths)** for fast, predictable results.
**With `--thorough`: Option C (Hybrid)** for deeper analysis.
**With `--full`: Option A (Recursive)** with strong warnings about time.

---

### Decision 3: Batch Size for Expression Evaluation

Based on existing ocls performance data, batching is crucial:

| Batch Size | Time for 100 paths | Expression Calls |
|------------|-------------------|------------------|
| 1          | ~5s               | 100              |
| 10         | ~0.5s             | 10               |
| 35         | ~0.15s            | 3                |
| 50         | ~0.12s            | 2                |

**Recommendation**: Use batch size of 35 (consistent with ocls) for testing writability.

---

## Implementation Architecture

### Command Interface

```
osbx [options] [path_prefix]

Options:
  --quick, -q       Test only most common paths (~20 paths)
  --thorough, -t    Enumerate subdirectories of writable paths
  --full, -f        Full recursive scan (very slow, use with caution)
  --sandbox-only    Use sandbox_check() instead of actual access test
  --output FILE     Write results to file instead of stdout
  --verbose, -v     Show all paths tested, not just writable ones
  --json            Output in JSON format for scripting

Arguments:
  path_prefix       Only test paths starting with this prefix (e.g., /var)

Examples:
  osbx                      # Quick scan of interesting paths
  osbx --quick              # Fastest scan (~20 paths)
  osbx /var                 # Only test paths under /var
  osbx --thorough           # Deep scan with subdirectory enumeration
  osbx --output writable.txt --json  # Save JSON results
```

### Core Implementation

```python
# scripts/objc_sandbox.py

from typing import Optional, List, Dict, Tuple

def get_container_path(frame: lldb.SBFrame) -> Optional[str]:
    """Get the app's sandbox container path."""
    expr = '(NSString *)NSHomeDirectory()'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        summary = result.GetSummary()
        if summary:
            return summary.strip('"@')
    return None

def get_temp_directory(frame: lldb.SBFrame) -> Optional[str]:
    """Get the app's temp directory."""
    expr = '(NSString *)NSTemporaryDirectory()'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        summary = result.GetSummary()
        if summary:
            return summary.strip('"@')
    return None

def batch_check_writable(
    frame: lldb.SBFrame,
    paths: List[str],
    batch_size: int = 35
) -> Dict[str, bool]:
    """
    Check writability of multiple paths in batched expressions.
    Returns dict mapping path -> is_writable.
    """
    results = {}

    for i in range(0, len(paths), batch_size):
        batch = paths[i:i + batch_size]

        # Escape paths for Objective-C string literals
        escaped_paths = [p.replace('\\', '\\\\').replace('"', '\\"') for p in batch]
        path_array = ', '.join(f'@"{p}"' for p in escaped_paths)

        expr = f'''
        (NSArray *)^{{
            NSFileManager *fm = [NSFileManager defaultManager];
            NSArray *paths = @[{path_array}];
            NSMutableArray *results = [NSMutableArray array];
            for (NSString *path in paths) {{
                BOOL writable = [fm isWritableFileAtPath:path];
                [results addObject:@(writable)];
            }}
            return results;
        }}()
        '''

        result = frame.EvaluateExpression(expr)
        if result.GetError().Success():
            # Parse NSArray of NSNumber(BOOL) results
            count = result.GetNumChildren()
            for j in range(min(count, len(batch))):
                child = result.GetChildAtIndex(j)
                is_writable = child.GetValueAsUnsigned() != 0
                results[batch[j]] = is_writable

    return results

def batch_sandbox_check(
    frame: lldb.SBFrame,
    paths: List[str],
    operation: str = "file-write-data",
    batch_size: int = 35,
    no_report: bool = True
) -> Dict[str, bool]:
    """
    Check sandbox policy for paths using sandbox_check() API.
    Returns dict mapping path -> is_allowed (True if sandbox allows).

    Note: This only checks sandbox policy, NOT POSIX permissions.
    """
    results = {}
    filter_type = "1"  # SANDBOX_FILTER_PATH
    if no_report:
        filter_type = "(1 | 0x40)"  # SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT

    for i in range(0, len(paths), batch_size):
        batch = paths[i:i + batch_size]

        escaped_paths = [p.replace('\\', '\\\\').replace('"', '\\"') for p in batch]
        path_array = ', '.join(f'@"{p}"' for p in escaped_paths)

        expr = f'''
        (NSArray *)^{{
            NSArray *paths = @[{path_array}];
            NSMutableArray *results = [NSMutableArray array];
            pid_t pid = getpid();
            for (NSString *path in paths) {{
                int result = sandbox_check(pid, "{operation}", {filter_type}, [path UTF8String]);
                [results addObject:@(result == 0)];  // 0 = allowed
            }}
            return results;
        }}()
        '''

        result = frame.EvaluateExpression(expr)
        if result.GetError().Success():
            count = result.GetNumChildren()
            for j in range(min(count, len(batch))):
                child = result.GetChildAtIndex(j)
                is_allowed = child.GetValueAsUnsigned() != 0
                results[batch[j]] = is_allowed

    return results

def enumerate_directory(
    frame: lldb.SBFrame,
    path: str,
    max_entries: int = 100
) -> Tuple[List[str], Optional[int]]:
    """
    Enumerate contents of a directory (shallow).
    Returns (list of full paths, error_code or None).
    """
    escaped_path = path.replace('\\', '\\\\').replace('"', '\\"')

    expr = f'''
    (NSDictionary *)^{{
        NSFileManager *fm = [NSFileManager defaultManager];
        NSError *error = nil;
        NSArray *contents = [fm contentsOfDirectoryAtPath:@"{escaped_path}" error:&error];
        if (error) {{
            return @{{@"error": @([error code])}};
        }}
        NSMutableArray *paths = [NSMutableArray array];
        NSUInteger limit = MIN(contents.count, (NSUInteger){max_entries});
        for (NSUInteger i = 0; i < limit; i++) {{
            NSString *fullPath = [@"{escaped_path}" stringByAppendingPathComponent:contents[i]];
            [paths addObject:fullPath];
        }}
        return @{{@"paths": paths, @"total": @(contents.count)}};
    }}()
    '''

    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        # Parse dictionary result
        error_child = result.GetChildMemberWithName("error")
        if error_child.IsValid():
            return [], error_child.GetValueAsSigned()

        paths_child = result.GetChildMemberWithName("paths")
        if paths_child.IsValid():
            paths = []
            for i in range(paths_child.GetNumChildren()):
                child = paths_child.GetChildAtIndex(i)
                path_str = child.GetSummary()
                if path_str:
                    paths.append(path_str.strip('"@'))
            return paths, None

    return [], -1  # Unknown error

def check_path_type(frame: lldb.SBFrame, path: str) -> str:
    """
    Determine if path is file, directory, symlink, or special.
    Returns: "file", "directory", "symlink", "device", "socket", "fifo", or "unknown"
    """
    escaped_path = path.replace('\\', '\\\\').replace('"', '\\"')

    expr = f'''
    (NSString *)^{{
        NSFileManager *fm = [NSFileManager defaultManager];
        NSDictionary *attrs = [fm attributesOfItemAtPath:@"{escaped_path}" error:nil];
        return attrs[NSFileType] ?: @"unknown";
    }}()
    '''

    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        type_str = result.GetSummary()
        if type_str:
            type_str = type_str.strip('"@')
            type_map = {{
                "NSFileTypeRegular": "file",
                "NSFileTypeDirectory": "directory",
                "NSFileTypeSymbolicLink": "symlink",
                "NSFileTypeCharacterSpecial": "device",
                "NSFileTypeBlockSpecial": "device",
                "NSFileTypeSocket": "socket",
                "NSFileTypeFIFO": "fifo",
            }}
            return type_map.get(type_str, "unknown")
    return "unknown"
```

### Output Format

**Default (Human-readable):**
```
Sandbox Writable Path Scan
══════════════════════════

Platform: iOS (device)
Container: /var/mobile/Containers/Data/Application/ABC123/
Temp: /private/var/mobile/Containers/Data/Application/ABC123/tmp/
Sandbox: active

Writable Paths (7 found):
  /var/mobile/Containers/Data/Application/ABC123/Documents/
  /var/mobile/Containers/Data/Application/ABC123/Library/
  /var/mobile/Containers/Data/Application/ABC123/Library/Caches/
  /var/mobile/Containers/Data/Application/ABC123/tmp/
  /private/var/mobile/Containers/Data/Application/ABC123/tmp/
  /dev/null (device)
  /dev/zero (device)

Non-Writable System Paths (as expected):
  /System/                          (SIP protected)
  /usr/bin/                         (SIP protected)
  /var/mobile/Library/SMS/          (sandbox denied)

Tested: 47 paths in 0.12s
```

**Verbose mode (`--verbose`):**
```
...
Testing: /var/mobile/Containers/Data/Application/ABC123/Documents/
  Result: writable (directory)
Testing: /System/
  Result: not writable (SIP protected)
Testing: /tmp/
  Result: writable → /private/tmp/ (symlink resolved)
Testing: /var/mobile/Library/SMS/
  Result: not writable (NSCocoaErrorDomain:257 - permission denied)
...
```

**JSON (`--json`):**
```json
{
  "platform": "iOS",
  "device_type": "device",
  "container": "/var/mobile/Containers/Data/Application/ABC123/",
  "temp_directory": "/private/var/mobile/Containers/Data/Application/ABC123/tmp/",
  "sandbox_active": true,
  "jailbroken": false,
  "writable_paths": [
    {
      "path": "/var/mobile/Containers/Data/Application/ABC123/Documents/",
      "type": "directory",
      "note": null
    },
    {
      "path": "/dev/null",
      "type": "device",
      "note": "special file"
    }
  ],
  "denied_paths": [
    {
      "path": "/System/",
      "reason": "SIP protected"
    },
    {
      "path": "/var/mobile/Library/SMS/",
      "reason": "sandbox denied"
    }
  ],
  "errors": [],
  "tested_count": 47,
  "writable_count": 7,
  "duration_seconds": 0.12,
  "scan_mode": "default"
}
```

---

## Platform Considerations

### macOS

| Feature | Availability |
|---------|--------------|
| NSFileManager | Full support |
| sandbox_check() | Available (private) |
| /tmp access | Typically allowed |
| Container paths | ~/Library/Containers/ |
| POSIX permissions | Primary control (non-sandboxed) |

**macOS-specific paths to test:**
```python
MACOS_PATHS = [
    "~/Library/Containers/{bundle_id}/Data/",
    "~/Library/Containers/{bundle_id}/Data/Documents/",
    "~/Library/Containers/{bundle_id}/Data/Library/",
    "~/Library/Application Support/",
    "~/Library/Caches/",
    "~/Library/Preferences/",
    "/private/var/folders/",  # User temp files (DARWIN_USER_TEMP_DIR)
    "/usr/local/",
    "/Applications/",
    "/Library/Application Support/",
    "~/Desktop/",
    "~/Documents/",
    "~/Downloads/",
]
```

**macOS App Sandbox entitlements affecting file access:**
```
com.apple.security.app-sandbox                    # Enable sandbox
com.apple.security.files.user-selected.read-only  # Open/Save panels (read)
com.apple.security.files.user-selected.read-write # Open/Save panels (read-write)
com.apple.security.files.downloads.read-only      # ~/Downloads (read)
com.apple.security.files.downloads.read-write     # ~/Downloads (read-write)
com.apple.security.files.pictures.read-only       # ~/Pictures (read)
com.apple.security.files.pictures.read-write      # ~/Pictures (read-write)
com.apple.security.files.music.read-only          # ~/Music (read)
com.apple.security.files.music.read-write         # ~/Music (read-write)
com.apple.security.files.movies.read-only         # ~/Movies (read)
com.apple.security.files.movies.read-write        # ~/Movies (read-write)
com.apple.security.application-groups             # Shared App Group containers
```

### iOS

| Feature | Availability |
|---------|--------------|
| NSFileManager | Full support |
| sandbox_check() | Limited (platform binaries only) |
| /tmp access | Container-scoped only |
| Container paths | /var/mobile/Containers/ |
| Jailbreak detection | May interfere |

**iOS sandbox container structure:**
```
/var/mobile/Containers/Data/Application/{UUID}/
├── Documents/              # User data, backed up to iCloud
├── Library/
│   ├── Application Support/  # App-specific data, backed up
│   ├── Caches/              # Cached data, NOT backed up, may be purged
│   └── Preferences/         # NSUserDefaults plist, backed up
├── tmp/                    # Temporary files, NOT backed up, may be purged
└── SystemData/             # System-managed data (iOS 15+)
```

**iOS-specific paths to test:**
```python
IOS_PATHS = [
    # App container
    "{{CONTAINER}}/Documents/",
    "{{CONTAINER}}/Library/",
    "{{CONTAINER}}/Library/Caches/",
    "{{CONTAINER}}/Library/Application Support/",
    "{{CONTAINER}}/Library/Preferences/",
    "{{CONTAINER}}/tmp/",

    # Shared containers (App Groups)
    "/var/mobile/Containers/Shared/AppGroup/{GROUP_ID}/",

    # System caches (may be writable with entitlements)
    "/var/mobile/Library/Caches/",

    # Common escape targets (should be denied)
    "/var/mobile/Library/",
    "/var/mobile/Media/",
    "/private/var/mobile/Library/SMS/",
    "/private/var/Keychains/",
]
```

**iOS key entitlements:**
```
com.apple.security.application-groups    # Shared containers between apps
keychain-access-groups                   # Shared keychain items
com.apple.developer.associated-domains   # Universal links, app clips
```

### Platform Detection

```python
def detect_platform(frame: lldb.SBFrame) -> str:
    """Detect iOS vs macOS from target triple and environment."""
    target = frame.GetThread().GetProcess().GetTarget()
    triple = target.GetTriple()

    # Check triple first
    if "ios" in triple:
        return "iOS"
    elif "macos" in triple:
        return "macOS"

    # arm64-apple-darwin could be iOS device OR Apple Silicon Mac
    # Disambiguate by checking home directory
    home = get_container_path(frame)
    if home:
        if home.startswith("/var/mobile/"):
            return "iOS"
        elif home.startswith("/Users/"):
            return "macOS"
        elif "/Library/Containers/" in home:
            return "macOS"

    # Check for iOS-specific path existence
    expr = '(BOOL)[[NSFileManager defaultManager] fileExistsAtPath:@"/var/mobile"]'
    result = frame.EvaluateExpression(expr)
    if result.GetValueAsUnsigned() == 1:
        return "iOS"

    return "macOS"  # Default to macOS

def is_simulator(frame: lldb.SBFrame) -> bool:
    """Detect if running in iOS Simulator (vs device)."""
    triple = frame.GetThread().GetProcess().GetTarget().GetTriple()
    # Simulator uses x86_64 or arm64 but with different sysroot
    if "simulator" in triple:
        return True

    # Alternative: check for simulator-specific environment
    expr = '(NSString *)[[NSProcessInfo processInfo] environment][@"SIMULATOR_DEVICE_NAME"]'
    result = frame.EvaluateExpression(expr)
    return result.GetSummary() is not None and result.GetSummary() != "nil"
```

### Detecting App Groups

```python
def get_app_group_containers(frame: lldb.SBFrame) -> List[str]:
    """Get shared App Group container paths if available."""
    paths = []

    # On iOS/macOS, app groups are accessible via:
    # [[NSFileManager defaultManager] containerURLForSecurityApplicationGroupIdentifier:]

    # First, we need to know the app's group identifiers from entitlements
    # This requires reading the embedded.mobileprovision or querying the process

    # Fallback: enumerate known shared container locations
    platform = detect_platform(frame)
    if platform == "iOS":
        base = "/var/mobile/Containers/Shared/AppGroup/"
    else:
        base = os.path.expanduser("~/Library/Group Containers/")

    # List directories at base path
    contents = enumerate_directory(frame, base, max_entries=50)
    return contents
```

---

## Error Handling & Edge Cases

### Process Not Running
```
error: Process must be running and stopped
hint: Attach to a process first with 'process attach' or run your app
```

### Process Not Sandboxed (macOS)
```
warning: Process does not appear to be sandboxed
All standard filesystem permissions apply (no sandbox restrictions)
Continuing with POSIX permission check...
```

Detection method:
```python
def is_sandboxed(frame: lldb.SBFrame) -> bool:
    """Check if process is running under sandbox."""
    # Method 1: Check for sandbox container path pattern
    home = get_container_path(frame)
    if home and "/Library/Containers/" in home:
        return True
    if home and "/var/mobile/Containers/" in home:
        return True

    # Method 2: Try sandbox_check for a known-denied path
    expr = '(int)sandbox_check(getpid(), "file-write-data", 1, "/System")'
    result = frame.EvaluateExpression(expr)
    # Non-zero return means sandbox denied it (process is sandboxed)
    return result.GetValueAsSigned() != 0
```

### Expression Evaluation Timeout
```
error: Expression timed out after 30s
hint: Try --quick mode or specify a narrower path_prefix
```

Mitigation:
- Set explicit timeout on `EvaluateExpression()` calls
- Reduce batch size if timeouts occur
- Consider `SetUnwindOnError(True)` to recover from stuck evaluations

### Permission Denied on Enumeration
When `contentsOfDirectoryAtPath:error:` fails, handle gracefully:

| NSCocoaErrorDomain Code | Meaning | Action |
|------------------------|---------|--------|
| 257 (NSFileReadNoPermissionError) | Permission denied | Skip, log in verbose |
| 260 (NSFileReadNoSuchFileError) | Path doesn't exist | Skip silently |
| 256 (NSFileReadUnknownError) | Unknown read error | Skip, warn in verbose |

**Important**: NSFileManager error messages can be misleading. Error 4 ("file doesn't exist") may indicate a missing *intermediate* directory rather than the target path. Always check `error.code`, not `localizedDescription`.

### Symbolic Links
- `isWritableFileAtPath:` tests the **target** of the symlink, not the link itself
- Symlink permissions (as shown by `ls -l`) are largely cosmetic on macOS - the kernel ignores them
- Even a symlink with `lrwxrwxrwx` (777) follows target permissions
- Edge case: dangling symlinks (target doesn't exist) return NO for writability
- Resolution: Test link path directly; use `lstat()` internally if needed
- Default: test link destination (matches `isWritableFileAtPath:` behavior)
- Optional `--no-follow-links` to skip symlink resolution

### Special Files
- `/dev/null` and `/dev/zero` are writable but not useful for data persistence
- Mark as "special" in output with `(device)` annotation
- Include in results (useful for sandbox profile validation)
- Other special files: `/dev/random`, `/dev/urandom`, named pipes (FIFOs)

### Hardlinks
- Multiple hardlinks to same inode share permissions
- Testing any hardlink tests the underlying file
- No special handling needed (same behavior as regular files)

---

## Performance Targets

| Mode | Paths Tested | Expected Time | Use Case |
|------|--------------|---------------|----------|
| `--quick` | ~20 | <0.1s | Quick verification |
| Default | ~100 | <0.5s | Standard audit |
| `--thorough` | ~500 | <2s | Security research |
| `--full` | 10K+ | 30s+ | Complete audit (warned) |

### Optimization Strategies

1. **Batch expressions**: 35 paths per call
2. **Early termination**: Stop enumeration at depth limit
3. **Caching**: Cache container path and temp directory
4. **Parallel enumeration**: Not feasible in LLDB (single expression thread)

---

---

## Advanced: Sandbox Extensions

Sandbox extensions are tokens that temporarily grant additional filesystem access to sandboxed processes. Understanding them is important for complete sandbox analysis.

### How Extensions Work

```c
// Extension issuing (by privileged process):
const char *sandbox_extension_issue_file(
    const char *extension_class,  // e.g., "com.apple.app-sandbox.read-write"
    const char *path,
    uint32_t flags
);

// Extension consumption (by sandboxed process):
int sandbox_extension_consume(const char *token);  // Returns -1 on failure
```

### Common Extension Classes

| Extension Class | Access Granted |
|-----------------|----------------|
| `com.apple.app-sandbox.read` | Read-only file access |
| `com.apple.app-sandbox.read-write` | Read-write file access |
| `com.apple.app-sandbox.read-by-process` | Process-scoped read access |

### When Extensions Are Granted

- **NSOpenPanel/NSSavePanel**: User file selection grants temporary access
- **Drag and drop**: Files dropped grant read access to destination
- **XPC services**: Some services issue extensions to clients
- **Security-scoped bookmarks**: Persistent access across app launches

### Detection in osbx

Extensions are challenging to detect because:
1. They're dynamic (granted at runtime, not in profile)
2. No public API to enumerate active extensions
3. A path may be writable due to extension, not profile

**Approach**: Note that `osbx` reports *current* writability, which includes active extensions. For profile-only analysis, use `--sandbox-only` mode with `sandbox_check()`.

---

## Security Considerations

### Sandbox Violation Logging
- `isWritableFileAtPath:` may log sandbox violations for denied paths
- Use `sandbox_check()` with `SANDBOX_CHECK_NO_REPORT` to avoid logging
- Document that running `osbx` may leave traces in system logs

### Information Disclosure
- Output reveals sandbox configuration
- Consider implications when sharing results
- `--json` output is machine-parseable (script-friendly but also attacker-friendly)

### Side Effects
- Read operations only; no writes attempted
- Directory enumeration may reveal file existence
- Consider `--dry-run` mode that only shows what would be tested

---

## Testing Strategy

### Unit Tests (pytest)
```python
# tests/unit/test_objc_sandbox.py

def test_path_list_generation():
    """Test that path templates are correctly expanded."""
    paths = generate_test_paths(container="/var/mobile/...")
    assert "{{CONTAINER}}" not in str(paths)

def test_batch_expression_building():
    """Test batched expression string generation."""
    expr = build_batch_check_expression(["/tmp", "/var"])
    assert "@\"/tmp\"" in expr
    assert "@\"/var\"" in expr
```

### Integration Tests
```python
# tests/test_osbx.py

def test_osbx_basic(lldb_session):
    """Test basic osbx output."""
    output = run_command("osbx --quick")
    assert "Writable Paths" in output
    assert "/dev/null" in output  # Always writable

def test_osbx_json(lldb_session):
    """Test JSON output format."""
    output = run_command("osbx --quick --json")
    data = json.loads(output)
    assert "writable_paths" in data
    assert isinstance(data["writable_paths"], list)

def test_osbx_container_resolution(lldb_session):
    """Test that container paths are resolved."""
    output = run_command("osbx --verbose")
    assert "{{CONTAINER}}" not in output
```

---

## Implementation Plan

### Phase 1: Core Functionality
1. Implement path list generation with platform detection
2. Implement batched `isWritableFileAtPath:` testing
3. Basic output formatting (human-readable)
4. Unit tests for path generation and expression building

### Phase 2: Enhanced Features
1. Add `--json` output format
2. Add `--thorough` mode with subdirectory enumeration
3. Add `--quick` mode with reduced path list
4. Integration tests

### Phase 3: Advanced Features
1. Add `--sandbox-only` mode with `sandbox_check()`
2. Add `--output` file writing
3. Add container path caching
4. Performance optimization

### Phase 4: Polish
1. Error message improvements
2. Documentation (README, help text)
3. Edge case handling
4. Security review

---

## Future Enhancements

### `osbx --diff`
Compare current writability against a baseline:
```
osbx --diff baseline.json
# Shows: +3 new writable paths, -1 path no longer writable
```

### `osbx --watch`
Monitor for sandbox extension grants in real-time:
```
osbx --watch
# [12:34:56] +write: /Users/user/Documents/file.txt (user selected)
```

### `osbx --entitlements`
Cross-reference with app entitlements:
```
osbx --entitlements
# Entitlement: com.apple.security.files.downloads.read-write
# Expected writable: ~/Downloads/ ✓
# Actual writable: ~/Downloads/ ✓
```

---

---

## Additional Edge Cases

### Race Conditions
- Filesystem state can change between check and use (TOCTOU)
- `osbx` reports point-in-time state, not guaranteed future access
- Dynamic sandbox extensions may be revoked at any time

### Case Sensitivity
- macOS filesystem is typically case-insensitive but case-preserving
- iOS filesystem is case-sensitive
- Path `/tmp/Test` and `/tmp/test` may or may not be the same

### Path Canonicalization
- `~/` expansion must happen within debugged process context
- Symlinks in paths (e.g., `/tmp` → `/private/tmp`) should be handled
- Use `NSString stringByResolvingSymlinksInPath` for canonical paths

```python
def canonicalize_path(frame: lldb.SBFrame, path: str) -> str:
    """Resolve symlinks and normalize path."""
    expr = f'(NSString *)[[@"{path}" stringByExpandingTildeInPath] stringByResolvingSymlinksInPath]'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        return result.GetSummary().strip('"')
    return path
```

### SIP-Protected Paths
System Integrity Protection (SIP) on macOS restricts even root from writing to:
- `/System/`
- `/usr/` (except `/usr/local/`)
- `/bin/`, `/sbin/`
- System applications

These paths will show as non-writable regardless of sandbox state.

### Mounted Volumes
- External drives: `/Volumes/{name}/`
- Network shares: `/Volumes/{name}/` or custom mount points
- DMG images: `/Volumes/{name}/` while mounted

Consider testing mounted volumes separately with `--include-volumes` flag.

### iOS Jailbreak Detection
On jailbroken devices:
- Sandbox may be bypassed or weakened
- Additional paths may be writable
- Detection: Check for `/Applications/Cydia.app`, `/private/var/stash`, etc.

```python
def is_jailbroken(frame: lldb.SBFrame) -> bool:
    """Detect common jailbreak indicators."""
    jailbreak_paths = [
        "/Applications/Cydia.app",
        "/Library/MobileSubstrate/",
        "/private/var/stash",
        "/usr/bin/ssh",
        "/etc/apt",
    ]
    for path in jailbreak_paths:
        expr = f'(BOOL)[[NSFileManager defaultManager] fileExistsAtPath:@"{path}"]'
        result = frame.EvaluateExpression(expr)
        if result.GetValueAsUnsigned() == 1:
            return True
    return False
```

---

## References

- [Apple: Configuring the macOS App Sandbox](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox)
- [Apple: Discovering and diagnosing App Sandbox violations](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations)
- [Apple: NSFileManager isWritableFileAtPath](https://developer.apple.com/documentation/foundation/nsfilemanager/1416680-iswritablefileatpath)
- [Apple: App Groups Entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups)
- [HackTricks: macOS Sandbox](https://book.hacktricks.xyz/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-sandbox)
- [HackTricks: macOS Sandbox Debug & Bypass](https://book.hacktricks.wiki/en/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-sandbox/macos-sandbox-debug-and-bypass/index.html)
- [A New Era of macOS Sandbox Escapes](https://jhftss.github.io/A-New-Era-of-macOS-Sandbox-Escapes/) - CVE research on sandbox_extension APIs
- [Igor's Techno Club: sandbox-exec](https://igorstechnoclub.com/sandbox-exec/)
- [GeoSn0w: A Long Evening with macOS Sandbox](https://geosn0w.github.io/A-Long-Evening-With-macOS's-Sandbox/)
- [Objection: Runtime Mobile Exploration](https://github.com/sensepost/objection)
- [sb_validator: sandbox_check() validation tool](https://github.com/Karmaz95/sb_validator)
- [RDProcess: apple_sandbox.h header](https://github.com/rodionovd/RDProcess/blob/master/apple_sandbox.h) - Private API definitions
- [8kSec: Reading iOS Sandbox Profiles](https://8ksec.io/reading-ios-sandbox-profiles/)
- [Apple: Accessing Files and Directories](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/AccessingFilesandDirectories/AccessingFilesandDirectories.html)
- [Ubrigens: A Whirlwind Tour of the Apple Sandbox](https://ubrigens.com/posts/sandbox_tour.html)
