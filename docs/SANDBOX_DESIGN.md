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
- **Limitation**: Requires root, checks single paths, not available on iOS

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
sandbox_check(getpid(), "file-write-data", SANDBOX_FILTER_PATH, path)
```

**Pros:**
- Tests sandbox policy directly without side effects
- No actual filesystem access attempted
- Can use `SANDBOX_CHECK_NO_REPORT` to suppress logs

**Cons:**
- Private API, may change between OS versions
- Only tests sandbox, not POSIX permissions
- Requires linking against private framework

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

def get_container_path(frame: lldb.SBFrame) -> Optional[str]:
    """Get the app's sandbox container path."""
    expr = '(NSString *)NSHomeDirectory()'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        return result.GetSummary().strip('"')
    return None

def get_temp_directory(frame: lldb.SBFrame) -> Optional[str]:
    """Get the app's temp directory."""
    expr = '(NSString *)NSTemporaryDirectory()'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        return result.GetSummary().strip('"')
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

        # Build batched expression
        path_array = ', '.join(f'@"{p}"' for p in batch)
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
        # Parse results...

    return results

def enumerate_directory(
    frame: lldb.SBFrame,
    path: str,
    max_entries: int = 100
) -> List[str]:
    """
    Enumerate contents of a directory (shallow).
    Returns list of full paths.
    """
    expr = f'''
    (NSArray *)^{{
        NSFileManager *fm = [NSFileManager defaultManager];
        NSError *error = nil;
        NSArray *contents = [fm contentsOfDirectoryAtPath:@"{path}" error:&error];
        if (error) return @[];
        NSMutableArray *paths = [NSMutableArray array];
        NSUInteger limit = MIN(contents.count, {max_entries});
        for (NSUInteger i = 0; i < limit; i++) {{
            [paths addObject:[NSString stringWithFormat:@"{path}/%@", contents[i]]];
        }}
        return paths;
    }}()
    '''
    # Execute and parse...
```

### Output Format

**Default (Human-readable):**
```
Sandbox Writable Path Scan
══════════════════════════

Container: /var/mobile/Containers/Data/Application/ABC123/

Writable Paths (7 found):
  /var/mobile/Containers/Data/Application/ABC123/Documents/
  /var/mobile/Containers/Data/Application/ABC123/Library/
  /var/mobile/Containers/Data/Application/ABC123/Library/Caches/
  /var/mobile/Containers/Data/Application/ABC123/tmp/
  /private/var/mobile/Containers/Data/Application/ABC123/tmp/
  /dev/null
  /dev/zero

Tested: 47 paths in 0.12s
```

**JSON (`--json`):**
```json
{
  "container": "/var/mobile/Containers/Data/Application/ABC123/",
  "writable_paths": [
    "/var/mobile/Containers/Data/Application/ABC123/Documents/",
    "/var/mobile/Containers/Data/Application/ABC123/Library/",
    ...
  ],
  "tested_count": 47,
  "duration_seconds": 0.12,
  "platform": "iOS",
  "sandbox_active": true
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
    "~/Library/Application Support/",
    "~/Library/Caches/",
    "/private/var/folders/",  # User temp files
    "/usr/local/",
    "/Applications/",
]
```

### iOS

| Feature | Availability |
|---------|--------------|
| NSFileManager | Full support |
| sandbox_check() | Limited (platform binary only) |
| /tmp access | Container-scoped only |
| Container paths | /var/mobile/Containers/ |
| Jailbreak detection | May interfere |

**iOS-specific paths to test:**
```python
IOS_PATHS = [
    "{{CONTAINER}}/Documents/",
    "{{CONTAINER}}/Library/",
    "{{CONTAINER}}/Library/Caches/",
    "{{CONTAINER}}/tmp/",
    "/var/mobile/Library/Caches/",
    "/var/mobile/Containers/Shared/AppGroup/",
]
```

### Platform Detection

```python
def detect_platform(frame: lldb.SBFrame) -> str:
    """Detect iOS vs macOS from target triple."""
    target = frame.GetThread().GetProcess().GetTarget()
    triple = target.GetTriple()

    if "ios" in triple or "arm64-apple-darwin" in triple:
        # Could be iOS device or simulator
        # Check for iOS-specific paths to confirm
        return "iOS"
    elif "macos" in triple or "x86_64-apple-darwin" in triple:
        return "macOS"
    else:
        return "unknown"
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

### Expression Evaluation Timeout
```
error: Expression timed out after 30s
hint: Try --quick mode or specify a narrower path_prefix
```

### Permission Denied on Enumeration
When `contentsOfDirectoryAtPath:` fails, silently skip and continue.
Log in `--verbose` mode: `(skipped: permission denied)`

### Symbolic Links
- Test the link path itself
- Optionally test resolved target with `--follow-links`
- Default: test link only (faster, avoids infinite loops)

### Special Files
- `/dev/null` and `/dev/zero` are writable but not useful for data
- Mark as "special" in output
- Include in results (useful for sandbox profile validation)

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

## References

- [Apple: Configuring the macOS App Sandbox](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox)
- [HackTricks: macOS Sandbox](https://book.hacktricks.xyz/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-sandbox)
- [Apple: NSFileManager isWritableFileAtPath](https://developer.apple.com/documentation/foundation/nsfilemanager/1416680-iswritablefileatpath)
- [Igor's Techno Club: sandbox-exec](https://igorstechnoclub.com/sandbox-exec/)
- [GeoSn0w: A Long Evening with macOS Sandbox](https://geosn0w.github.io/A-Long-Evening-With-macOS's-Sandbox/)
- [Objection: Runtime Mobile Exploration](https://github.com/sensepost/objection)
- [Apple: Accessing Files and Directories](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/AccessingFilesandDirectories/AccessingFilesandDirectories.html)
