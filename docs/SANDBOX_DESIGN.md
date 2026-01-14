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
  --filter PATTERN  Only test paths matching glob/regex pattern (e.g., "/var/**", ".*Library.*")
  --log FILE        Write detailed per-path check log to file (path, result, reason)

Arguments:
  path_prefix       Only test paths starting with this prefix (e.g., /var)

Examples:
  osbx                      # Quick scan of interesting paths
  osbx --quick              # Fastest scan (~20 paths)
  osbx /var                 # Only test paths under /var
  osbx --thorough           # Deep scan with subdirectory enumeration
  osbx --output writable.txt --json  # Save JSON results
  osbx --filter "/tmp/**"   # Only test paths under /tmp
  osbx --filter ".*Caches.*"  # Only test paths containing "Caches"
  osbx --log scan.log       # Save detailed check log for debugging
  osbx --log scan.log --filter "/var/**" --thorough  # Filtered thorough scan with logging
```

### Filter Option (`--filter`)

The `--filter` option restricts scanning to a subset of paths, useful for:
- Faster targeted scans
- Debugging specific directories
- Testing hypothesis about specific paths

**Filter syntax:**
- Glob patterns: `/var/**`, `/tmp/*`, `~/Library/Caches/*`
- Regex patterns: `.*Library.*`, `^/var/mobile/.*`
- Multiple filters: `--filter "/tmp/**" --filter "/var/tmp/**"` (OR logic)

```python
import fnmatch
import re

def matches_filter(path: str, filters: List[str]) -> bool:
    """Check if path matches any of the filter patterns."""
    if not filters:
        return True  # No filter = match all

    for pattern in filters:
        # Try glob first
        if fnmatch.fnmatch(path, pattern):
            return True
        # Try regex
        try:
            if re.match(pattern, path):
                return True
        except re.error:
            pass  # Invalid regex, skip

    return False
```

### Detailed Log Option (`--log`)

The `--log` option writes a comprehensive per-path check log for debugging and analysis.

**Log format (TSV):**
```
# osbx scan log - 2024-01-15T10:30:00Z
# Platform: macOS, Container: /Users/test/Library/Containers/com.example.app/Data
# Filter: /var/**
# Paths tested: 47, Writable: 7, Duration: 0.12s
PATH	RESULT	TYPE	REASON	DETAILS
/var/tmp	writable	directory	-	-
/var/log	not_writable	directory	permission_denied	NSCocoaErrorDomain:257
/var/folders/xx/xxx/T	writable	directory	-	symlink_target=/private/var/folders/xx/xxx/T
/System	not_writable	directory	sip_protected	-
/var/mobile/Library/SMS	not_writable	directory	sandbox_denied	sandbox_check returned 1
/dev/null	writable	device	-	special_file
/nonexistent	skipped	-	not_found	NSCocoaErrorDomain:260
```

**Log reasons:**
| Reason | Description |
|--------|-------------|
| `-` | Path is writable, no restriction |
| `permission_denied` | POSIX permission denied (NSCocoaErrorDomain:257) |
| `sandbox_denied` | Sandbox policy blocked access |
| `sip_protected` | System Integrity Protection (macOS) |
| `not_found` | Path does not exist |
| `timeout` | Expression evaluation timed out |
| `symlink_dangling` | Symlink target does not exist |
| `unknown_error` | Unexpected error during check |

```python
class ScanLogger:
    """Writes detailed per-path check log."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.entries: List[Dict] = []
        self.start_time = time.time()

    def log_check(self, path: str, result: str, path_type: str,
                  reason: str, details: str = "-"):
        """Record a single path check result."""
        self.entries.append({
            "path": path,
            "result": result,  # writable, not_writable, skipped, error
            "type": path_type,  # directory, file, device, symlink, unknown
            "reason": reason,
            "details": details,
        })

    def write(self, metadata: Dict):
        """Write log file with header and entries."""
        with open(self.log_path, 'w') as f:
            # Header
            f.write(f"# osbx scan log - {datetime.utcnow().isoformat()}Z\n")
            f.write(f"# Platform: {metadata['platform']}, Container: {metadata['container']}\n")
            if metadata.get('filter'):
                f.write(f"# Filter: {metadata['filter']}\n")
            duration = time.time() - self.start_time
            writable = sum(1 for e in self.entries if e['result'] == 'writable')
            f.write(f"# Paths tested: {len(self.entries)}, Writable: {writable}, Duration: {duration:.2f}s\n")
            f.write("PATH\tRESULT\tTYPE\tREASON\tDETAILS\n")

            # Entries
            for entry in self.entries:
                f.write(f"{entry['path']}\t{entry['result']}\t{entry['type']}\t{entry['reason']}\t{entry['details']}\n")
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

### Sandboxed Test Binary

To enable predictable sandbox testing, we build a variant of the `helloworld` test binary that opts into a known sandbox profile. This provides deterministic expected results for integration tests.

#### Test Binary: `helloworld_sandboxed`

**Location:** `testbins/helloworld_sandboxed/`

**Sandbox Profile:** `testbins/helloworld_sandboxed/sandbox.sb`
```scheme
;; Minimal sandbox profile for osbx testing
;; Predictable: allows specific paths, denies others

(version 1)
(deny default)

;; Allow basic process execution
(allow process-exec*)
(allow process-fork)
(allow signal)
(allow sysctl-read)

;; Allow reading system libraries and frameworks
(allow file-read*
    (subpath "/usr/lib")
    (subpath "/System/Library/Frameworks")
    (subpath "/System/Library/PrivateFrameworks")
    (subpath "/Library/Frameworks"))

;; Allow reading /dev for special files
(allow file-read* (subpath "/dev"))
(allow file-write* (literal "/dev/null"))
(allow file-write* (literal "/dev/zero"))

;; WRITABLE: Specific test directories (created by test harness)
(allow file-read* file-write*
    (subpath (param "SANDBOX_WRITABLE_DIR")))

;; WRITABLE: System temp (for realistic sandbox behavior)
(allow file-read* file-write*
    (subpath "/private/tmp/osbx_test"))

;; READABLE but not writable: test read-only directory
(allow file-read*
    (subpath (param "SANDBOX_READONLY_DIR")))

;; DENIED: Everything else (default deny)
```

**Source:** `testbins/helloworld_sandboxed/main.m`
```objective-c
// helloworld_sandboxed - Test binary with predictable sandbox profile

#import <Foundation/Foundation.h>
#include <sandbox.h>

int main(int argc, char *argv[]) {
    @autoreleasepool {
        // Read sandbox profile path from environment or use default
        NSString *profilePath = [[NSProcessInfo processInfo] environment][@"SANDBOX_PROFILE"];
        if (!profilePath) {
            profilePath = @"sandbox.sb";
        }

        // Read sandbox parameters from environment
        NSString *writableDir = [[NSProcessInfo processInfo] environment][@"SANDBOX_WRITABLE_DIR"]
                                ?: @"/tmp/osbx_test_writable";
        NSString *readonlyDir = [[NSProcessInfo processInfo] environment][@"SANDBOX_READONLY_DIR"]
                                ?: @"/tmp/osbx_test_readonly";

        // Load and apply sandbox profile
        NSString *profile = [NSString stringWithContentsOfFile:profilePath
                                                     encoding:NSUTF8StringEncoding
                                                        error:nil];
        if (profile) {
            const char *params[] = {
                "SANDBOX_WRITABLE_DIR", [writableDir UTF8String],
                "SANDBOX_READONLY_DIR", [readonlyDir UTF8String],
                NULL
            };

            char *error = NULL;
            if (sandbox_init_with_parameters([profile UTF8String], 0, params, &error) != 0) {
                NSLog(@"Sandbox init failed: %s", error ? error : "unknown");
                sandbox_free_error(error);
                return 1;
            }
            NSLog(@"Sandbox initialized with profile: %@", profilePath);
        } else {
            NSLog(@"Warning: No sandbox profile loaded, running unsandboxed");
        }

        // Stay alive for LLDB to attach
        NSLog(@"helloworld_sandboxed ready (PID: %d)", getpid());
        NSLog(@"Writable: %@", writableDir);
        NSLog(@"Readonly: %@", readonlyDir);

        // Wait for debugger
        [[NSRunLoop currentRunLoop] run];
    }
    return 0;
}
```

**Build Configuration:** `testbins/helloworld_sandboxed/Makefile`
```makefile
# Build sandboxed test binary for osbx testing

BINARY = helloworld_sandboxed
SOURCES = main.m
FRAMEWORKS = -framework Foundation
CFLAGS = -arch arm64 -arch x86_64 -mmacosx-version-min=12.0

all: $(BINARY)

$(BINARY): $(SOURCES)
	clang $(CFLAGS) $(FRAMEWORKS) -o $@ $<

clean:
	rm -f $(BINARY)

.PHONY: all clean
```

#### Test Harness Setup

```python
# tests/conftest.py additions

import os
import tempfile
import shutil
import subprocess

@pytest.fixture
def sandboxed_test_dirs():
    """Create test directories with known permissions."""
    base = tempfile.mkdtemp(prefix="osbx_test_")
    writable = os.path.join(base, "writable")
    readonly = os.path.join(base, "readonly")

    os.makedirs(writable)
    os.makedirs(readonly)

    # Create test files
    open(os.path.join(writable, "test.txt"), 'w').close()
    open(os.path.join(readonly, "test.txt"), 'w').close()

    # Make readonly actually read-only
    os.chmod(readonly, 0o555)
    os.chmod(os.path.join(readonly, "test.txt"), 0o444)

    # Also create the /private/tmp/osbx_test directory (profile expects it)
    os.makedirs("/private/tmp/osbx_test", exist_ok=True)

    yield {
        "base": base,
        "writable": writable,
        "readonly": readonly,
        "system_writable": "/private/tmp/osbx_test",
    }

    # Cleanup
    os.chmod(readonly, 0o755)  # Restore permissions for deletion
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree("/private/tmp/osbx_test", ignore_errors=True)

@pytest.fixture
def sandboxed_lldb_session(sandboxed_test_dirs):
    """Launch sandboxed test binary and attach LLDB."""
    env = os.environ.copy()
    env["SANDBOX_WRITABLE_DIR"] = sandboxed_test_dirs["writable"]
    env["SANDBOX_READONLY_DIR"] = sandboxed_test_dirs["readonly"]
    env["SANDBOX_PROFILE"] = "testbins/helloworld_sandboxed/sandbox.sb"

    # Launch the sandboxed binary
    proc = subprocess.Popen(
        ["testbins/helloworld_sandboxed/helloworld_sandboxed"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Attach LLDB
    session = LLDBTestSession()
    session.attach(proc.pid)

    yield session, sandboxed_test_dirs

    # Cleanup
    session.detach()
    proc.terminate()
    proc.wait()
```

#### Bootstrap Integration Tests

```python
# tests/test_osbx_sandboxed.py

"""Integration tests for osbx using sandboxed test binary."""

import json

class TestOsbxSandboxed:
    """Test osbx command with predictable sandbox environment."""

    def test_sandbox_detection(self, sandboxed_lldb_session):
        """Verify osbx detects sandboxed process."""
        session, dirs = sandboxed_lldb_session
        output = session.run_command("osbx --quick --json")
        data = json.loads(output)
        assert data["sandbox_active"] is True

    def test_expected_writable_paths(self, sandboxed_lldb_session):
        """Verify expected paths are reported as writable."""
        session, dirs = sandboxed_lldb_session
        output = session.run_command(f"osbx --filter '{dirs['writable']}/**' --json")
        data = json.loads(output)

        writable_paths = [p["path"] for p in data["writable_paths"]]
        assert dirs["writable"] in writable_paths or \
               any(p.startswith(dirs["writable"]) for p in writable_paths)

    def test_expected_denied_paths(self, sandboxed_lldb_session):
        """Verify read-only paths are NOT writable."""
        session, dirs = sandboxed_lldb_session
        output = session.run_command(f"osbx --filter '{dirs['readonly']}/**' --json")
        data = json.loads(output)

        writable_paths = [p["path"] for p in data["writable_paths"]]
        # Read-only dir should NOT appear in writable paths
        assert dirs["readonly"] not in writable_paths
        assert not any(p.startswith(dirs["readonly"]) for p in writable_paths)

    def test_system_paths_denied(self, sandboxed_lldb_session):
        """Verify system paths are denied by sandbox."""
        session, dirs = sandboxed_lldb_session
        output = session.run_command("osbx --filter '/System/**' --json")
        data = json.loads(output)

        # /System should be denied
        assert len(data["writable_paths"]) == 0
        denied_paths = [p["path"] for p in data["denied_paths"]]
        assert "/System" in denied_paths or "/System/" in denied_paths

    def test_dev_null_writable(self, sandboxed_lldb_session):
        """Verify /dev/null is writable (profile allows it)."""
        session, dirs = sandboxed_lldb_session
        output = session.run_command("osbx --filter '/dev/null' --json")
        data = json.loads(output)

        writable_paths = [p["path"] for p in data["writable_paths"]]
        assert "/dev/null" in writable_paths

    def test_filter_narrows_scan(self, sandboxed_lldb_session):
        """Verify --filter reduces paths tested."""
        session, dirs = sandboxed_lldb_session

        # Full scan
        full_output = session.run_command("osbx --json")
        full_data = json.loads(full_output)

        # Filtered scan
        filtered_output = session.run_command(f"osbx --filter '{dirs['writable']}/**' --json")
        filtered_data = json.loads(filtered_output)

        assert filtered_data["tested_count"] < full_data["tested_count"]

    def test_log_output(self, sandboxed_lldb_session, tmp_path):
        """Verify --log produces detailed output."""
        session, dirs = sandboxed_lldb_session
        log_path = tmp_path / "scan.log"

        session.run_command(f"osbx --log {log_path}")

        assert log_path.exists()
        content = log_path.read_text()

        # Verify log format
        assert "PATH\tRESULT\tTYPE\tREASON\tDETAILS" in content
        assert "# osbx scan log" in content

        # Verify entries exist
        lines = [l for l in content.split('\n') if l and not l.startswith('#')]
        assert len(lines) > 1  # Header + at least one entry

    def test_log_with_filter(self, sandboxed_lldb_session, tmp_path):
        """Verify --log respects --filter."""
        session, dirs = sandboxed_lldb_session
        log_path = tmp_path / "scan.log"

        session.run_command(f"osbx --filter '/tmp/**' --log {log_path}")

        content = log_path.read_text()
        # All non-header lines should have paths starting with /tmp or /private/tmp
        for line in content.split('\n'):
            if line and not line.startswith('#') and not line.startswith('PATH'):
                path = line.split('\t')[0]
                assert path.startswith('/tmp') or path.startswith('/private/tmp'), \
                    f"Path {path} doesn't match filter /tmp/**"
```

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

def test_filter_matching_glob():
    """Test glob pattern matching."""
    assert matches_filter("/tmp/foo", ["/tmp/**"])
    assert matches_filter("/tmp/bar/baz", ["/tmp/**"])
    assert not matches_filter("/var/tmp", ["/tmp/**"])

def test_filter_matching_regex():
    """Test regex pattern matching."""
    assert matches_filter("/var/mobile/Library/Caches", [".*Caches.*"])
    assert not matches_filter("/var/mobile/Documents", [".*Caches.*"])

def test_filter_multiple():
    """Test multiple filter patterns (OR logic)."""
    assert matches_filter("/tmp/foo", ["/tmp/**", "/var/**"])
    assert matches_filter("/var/bar", ["/tmp/**", "/var/**"])
    assert not matches_filter("/System/foo", ["/tmp/**", "/var/**"])
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

### Phase 0: Test Infrastructure
1. Build `helloworld_sandboxed` test binary with predictable sandbox profile
2. Create sandbox profile (`sandbox.sb`) with known writable/denied paths
3. Set up test fixtures for sandboxed LLDB sessions
4. Bootstrap integration tests that verify sandbox detection

### Phase 1: Core Functionality
1. Implement path list generation with platform detection
2. Implement batched `isWritableFileAtPath:` testing
3. Basic output formatting (human-readable)
4. Implement `--filter` option for path pattern matching
5. Unit tests for path generation, expression building, and filter matching

### Phase 2: Enhanced Features
1. Add `--json` output format
2. Add `--thorough` mode with subdirectory enumeration
3. Add `--quick` mode with reduced path list
4. Add `--log` detailed logging output
5. Integration tests with sandboxed binary

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
5. CI integration for sandboxed tests

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
