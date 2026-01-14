#!/usr/bin/env python3
"""
LLDB script for scanning sandbox filesystem access - osbx command.

Efficiently scans the filesystem to determine which paths are writable
from within the currently debugged process's sandbox.

Usage:
    osbx [options] [path_prefix]

Options:
    --quick, -q       Test only most common paths (~20 paths)
    --verbose, -v     Show all paths tested, not just writable ones
    --json            Output in JSON format for scripting
    --filter PATTERN  Only test paths matching glob/regex pattern
    --ignore PATTERN  Skip paths matching glob/regex pattern
    --no-default-ignore  Don't apply default ignore patterns

Arguments:
    path_prefix       Only test paths starting with this prefix (e.g., /var)

Examples:
    osbx                      # Quick scan of interesting paths
    osbx --quick              # Fastest scan (~20 paths)
    osbx /var                 # Only test paths under /var
    osbx --filter "/tmp/**"   # Only test paths under /tmp
    osbx --json               # JSON output for scripting

Use cases:
    - Security Research: Audit sandbox profiles for overly permissive rules
    - App Development: Verify sandbox entitlements are correctly configured
    - Reverse Engineering: Understand what data an app can persist
    - CTF/Pentesting: Identify writable paths for privilege escalation
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Try to import lldb - may not be available during unit tests
try:
    import lldb
except ImportError:
    lldb = None

# Batch size for testing writability (consistent with ocls)
DEFAULT_BATCH_SIZE = 35

# Default ignore patterns (skip known-inaccessible large directories)
DEFAULT_IGNORE_PATTERNS = [
    "/System/**",  # macOS system (SIP protected, ~500K files)
    "/usr/**",  # Unix system (SIP protected)
    "/bin/**",  # System binaries
    "/sbin/**",  # System binaries
    "*.app/Contents/*",  # Inside app bundles (read-only)
    "*.framework/*",  # Inside frameworks (read-only)
    "/Library/Developer/**",  # Xcode caches
    "*/.git/*",  # Git internals
    "*/node_modules/*",  # NPM packages
    "/cores/**",  # Core dumps
]

# Quick scan paths (~20 most important paths)
QUICK_PATHS = [
    # App container (templates resolved at runtime)
    "{{CONTAINER}}/Documents",
    "{{CONTAINER}}/Library",
    "{{CONTAINER}}/Library/Caches",
    "{{CONTAINER}}/tmp",
    # System temp directories
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    # Special files
    "/dev/null",
    "/dev/zero",
]

# Full path list for default scan
INTERESTING_PATHS_MACOS = [
    # App container (resolved at runtime)
    "{{CONTAINER}}/Documents",
    "{{CONTAINER}}/Library",
    "{{CONTAINER}}/Library/Caches",
    "{{CONTAINER}}/Library/Application Support",
    "{{CONTAINER}}/Library/Preferences",
    "{{CONTAINER}}/tmp",
    # User directories
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
    "~/Library/Caches",
    "~/Library/Application Support",
    "~/Library/Preferences",
    # System temp directories
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    "/private/var/tmp",
    "/var/folders",
    "/private/var/folders",
    # Common system paths
    "/usr/local",
    "/Applications",
    "/Library/Application Support",
    # Special files
    "/dev/null",
    "/dev/zero",
]

INTERESTING_PATHS_IOS = [
    # App container (resolved at runtime)
    "{{CONTAINER}}/Documents",
    "{{CONTAINER}}/Library",
    "{{CONTAINER}}/Library/Caches",
    "{{CONTAINER}}/Library/Application Support",
    "{{CONTAINER}}/Library/Preferences",
    "{{CONTAINER}}/tmp",
    # Shared containers
    "/var/mobile/Containers/Shared/AppGroup",
    # System caches
    "/var/mobile/Library/Caches",
    # Common escape targets (should be denied)
    "/var/mobile/Library",
    "/var/mobile/Media",
    "/private/var/mobile/Library/SMS",
    "/private/var/Keychains",
    # Temp
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    # Special files
    "/dev/null",
    "/dev/zero",
]


# ============================================================================
# Pure Python Functions (Unit Testable)
# ============================================================================


def matches_filter(path: str, filters: List[str]) -> bool:
    """
    Check if path matches any of the filter patterns.

    Args:
        path: The path to check
        filters: List of glob or regex patterns

    Returns:
        True if path matches any filter (or if filters is empty)
    """
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


def should_skip_path(path: str, ignore_patterns: List[str]) -> bool:
    """
    Check if path should be skipped based on ignore patterns.

    Args:
        path: The path to check
        ignore_patterns: List of glob or regex patterns to ignore

    Returns:
        True if path should be skipped
    """
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        try:
            if re.search(pattern, path):
                return True
        except re.error:
            pass
    return False


def escape_objc_string(s: str) -> str:
    """
    Escape a string for use in Objective-C string literals.

    Args:
        s: String to escape

    Returns:
        Escaped string safe for @"..." literals
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate_test_paths(
    container: Optional[str],
    temp_dir: Optional[str],
    platform: str,
    quick: bool = False,
) -> List[str]:
    """
    Generate list of paths to test for writability.

    Args:
        container: App container path (e.g., /var/mobile/Containers/Data/Application/ABC123)
        temp_dir: App temp directory
        platform: "iOS" or "macOS"
        quick: If True, return only the quick scan paths

    Returns:
        List of paths to test (with {{CONTAINER}} replaced)
    """
    if quick:
        base_paths = QUICK_PATHS.copy()
    else:
        base_paths = INTERESTING_PATHS_IOS.copy() if platform == "iOS" else INTERESTING_PATHS_MACOS.copy()

    # Expand templates
    expanded = []
    for path in base_paths:
        if "{{CONTAINER}}" in path:
            if container:
                expanded.append(path.replace("{{CONTAINER}}", container))
        elif path.startswith("~"):
            # Expand ~ to container for sandboxed apps
            if container:
                expanded.append(path.replace("~", container))
            else:
                # Keep ~ for non-sandboxed (will be expanded in-process)
                expanded.append(path)
        else:
            expanded.append(path)

    # Add temp directory if available and not already included
    if temp_dir and temp_dir not in expanded:
        expanded.append(temp_dir)

    return expanded


def format_output_human(
    writable_paths: List[Dict[str, Any]],
    denied_paths: List[Dict[str, Any]],
    platform: str,
    container: Optional[str],
    temp_dir: Optional[str],
    sandbox_active: bool,
    tested_count: int,
    duration: float,
    verbose: bool = False,
) -> str:
    """
    Format scan results for human-readable output.

    Args:
        writable_paths: List of {path, type, note} dicts
        denied_paths: List of {path, reason} dicts
        platform: "iOS" or "macOS"
        container: App container path
        temp_dir: App temp directory
        sandbox_active: Whether sandbox is active
        tested_count: Number of paths tested
        duration: Scan duration in seconds
        verbose: Show all paths, not just writable

    Returns:
        Formatted output string
    """
    lines = []

    # Header
    lines.append("Sandbox Writable Path Scan")
    lines.append("=" * 26)
    lines.append("")
    lines.append(f"Platform: {platform}")
    if container:
        lines.append(f"Container: {container}")
    if temp_dir:
        lines.append(f"Temp: {temp_dir}")
    lines.append(f"Sandbox: {'active' if sandbox_active else 'not detected'}")
    lines.append("")

    # Writable paths
    if writable_paths:
        lines.append(f"Writable Paths ({len(writable_paths)} found):")
        for p in writable_paths:
            path_str = p["path"]
            if p.get("type") == "device":
                path_str += " (device)"
            elif p.get("type") == "symlink" and p.get("note"):
                path_str += f" \033[90m({p['note']})\033[0m"
            lines.append(f"  {path_str}")
    else:
        lines.append("Writable Paths: none found")

    # Denied paths (only in verbose mode or if no writable paths)
    if verbose and denied_paths:
        lines.append("")
        lines.append(f"Non-Writable Paths ({len(denied_paths)} found):")
        for p in denied_paths:
            reason = p.get("reason", "denied")
            # Truncate reason if too long
            if len(reason) > 30:
                reason = reason[:27] + "..."
            lines.append(f"  {p['path']:<40} \033[90m({reason})\033[0m")

    # Summary
    lines.append("")
    lines.append(f"Tested: {tested_count} paths in {duration:.2f}s")

    return "\n".join(lines)


def format_output_json(
    writable_paths: List[Dict[str, Any]],
    denied_paths: List[Dict[str, Any]],
    platform: str,
    container: Optional[str],
    temp_dir: Optional[str],
    sandbox_active: bool,
    tested_count: int,
    duration: float,
    scan_mode: str = "default",
) -> str:
    """
    Format scan results as JSON.

    Returns:
        JSON string
    """
    data = {
        "platform": platform,
        "container": container,
        "temp_directory": temp_dir,
        "sandbox_active": sandbox_active,
        "writable_paths": writable_paths,
        "denied_paths": denied_paths,
        "tested_count": tested_count,
        "writable_count": len(writable_paths),
        "duration_seconds": round(duration, 3),
        "scan_mode": scan_mode,
    }
    return json.dumps(data, indent=2)


# ============================================================================
# LLDB-Dependent Functions
# ============================================================================


def get_container_path(frame) -> Optional[str]:
    """Get the app's sandbox container path using NSHomeDirectory()."""
    if not lldb:
        return None

    expr = "(NSString *)NSHomeDirectory()"
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        summary = result.GetSummary()
        if summary:
            # Remove quotes and @ prefix
            return summary.strip('"@')
    return None


def get_temp_directory(frame) -> Optional[str]:
    """Get the app's temp directory using NSTemporaryDirectory()."""
    if not lldb:
        return None

    expr = "(NSString *)NSTemporaryDirectory()"
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        summary = result.GetSummary()
        if summary:
            return summary.strip('"@')
    return None


def detect_platform(frame) -> str:
    """
    Detect iOS vs macOS from target triple and environment.

    Returns:
        "iOS" or "macOS"
    """
    if not lldb:
        return "macOS"

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


def is_sandboxed(frame) -> bool:
    """
    Check if process is running under sandbox.

    Returns:
        True if sandboxed
    """
    if not lldb:
        return False

    # Method 1: Check for sandbox container path pattern
    home = get_container_path(frame)
    if home:
        if "/Library/Containers/" in home:
            return True
        if "/var/mobile/Containers/" in home:
            return True

    # Method 2: Try sandbox_check for a known-denied path
    # sandbox_check returns 0 if allowed, non-zero if denied
    expr = '(int)sandbox_check(getpid(), "file-write-data", 1, "/System")'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        # Non-zero return means sandbox denied it (process is sandboxed)
        return result.GetValueAsSigned() != 0

    return False


def check_path_type(frame, path: str) -> str:
    """
    Determine if path is file, directory, symlink, or special.

    Returns:
        "file", "directory", "symlink", "device", "socket", "fifo", or "unknown"
    """
    if not lldb:
        return "unknown"

    escaped_path = escape_objc_string(path)

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
            type_map = {
                "NSFileTypeRegular": "file",
                "NSFileTypeDirectory": "directory",
                "NSFileTypeSymbolicLink": "symlink",
                "NSFileTypeCharacterSpecial": "device",
                "NSFileTypeBlockSpecial": "device",
                "NSFileTypeSocket": "socket",
                "NSFileTypeFIFO": "fifo",
            }
            return type_map.get(type_str, "unknown")
    return "unknown"


def batch_check_writable(frame, paths: List[str], batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, bool]:
    """
    Check writability of multiple paths in batched expressions.

    Args:
        frame: LLDB SBFrame
        paths: List of paths to check
        batch_size: Number of paths per batch

    Returns:
        Dict mapping path -> is_writable
    """
    if not lldb:
        return {}

    results = {}

    for i in range(0, len(paths), batch_size):
        batch = paths[i : i + batch_size]

        # Escape paths for Objective-C string literals
        escaped_paths = [escape_objc_string(p) for p in batch]
        path_array = ", ".join(f'@"{p}"' for p in escaped_paths)

        expr = f"""
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
        """

        result = frame.EvaluateExpression(expr)
        if result.GetError().Success():
            # Parse NSArray of NSNumber(BOOL) results
            count = result.GetNumChildren()
            for j in range(min(count, len(batch))):
                child = result.GetChildAtIndex(j)
                is_writable = child.GetValueAsUnsigned() != 0
                results[batch[j]] = is_writable
        else:
            # Mark all as unknown/not writable on error
            for path in batch:
                results[path] = False

    return results


def canonicalize_path(frame, path: str) -> str:
    """
    Resolve symlinks and normalize path.

    Args:
        frame: LLDB SBFrame
        path: Path to canonicalize

    Returns:
        Canonical path (or original if resolution fails)
    """
    if not lldb:
        return path

    escaped_path = escape_objc_string(path)

    expr = f'(NSString *)[[@"{escaped_path}" stringByExpandingTildeInPath] stringByResolvingSymlinksInPath]'
    result = frame.EvaluateExpression(expr)
    if result.GetError().Success():
        summary = result.GetSummary()
        if summary:
            return summary.strip('"@')
    return path


def deduplicate_paths(frame, paths: List[str]) -> List[str]:
    """
    Remove duplicate paths after resolving symlinks.

    Args:
        frame: LLDB SBFrame
        paths: List of paths to deduplicate

    Returns:
        List of unique paths (keeping original form)
    """
    seen_canonical = set()
    unique_paths = []

    for path in paths:
        canonical = canonicalize_path(frame, path)
        if canonical not in seen_canonical:
            seen_canonical.add(canonical)
            unique_paths.append(path)

    return unique_paths


# ============================================================================
# Main Command
# ============================================================================


def osbx_command(
    debugger,
    command: str,
    result,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Scan sandbox filesystem access to find writable paths.

    Usage: osbx [options] [path_prefix]
    """
    if not lldb:
        result.SetError("LLDB not available")
        return

    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse arguments
    args = command.strip().split()
    quick = "--quick" in args or "-q" in args
    verbose = "--verbose" in args or "-v" in args
    output_json = "--json" in args
    no_default_ignore = "--no-default-ignore" in args

    # Parse --filter and --ignore options
    filters = []
    ignores = [] if no_default_ignore else DEFAULT_IGNORE_PATTERNS.copy()
    path_prefix = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--filter" and i + 1 < len(args):
            filters.append(args[i + 1])
            i += 1
        elif arg.startswith("--filter="):
            filters.append(arg.split("=", 1)[1])
        elif arg == "--ignore" and i + 1 < len(args):
            ignores.append(args[i + 1])
            i += 1
        elif arg.startswith("--ignore="):
            ignores.append(arg.split("=", 1)[1])
        elif not arg.startswith("-") and not path_prefix:
            path_prefix = arg
        i += 1

    # Get current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    start_time = time.time()

    # Detect platform and environment
    platform = detect_platform(frame)
    container = get_container_path(frame)
    temp_dir = get_temp_directory(frame)
    sandbox_active = is_sandboxed(frame)

    # Generate paths to test
    paths = generate_test_paths(container, temp_dir, platform, quick=quick)

    # Apply path prefix filter
    if path_prefix:
        paths = [p for p in paths if p.startswith(path_prefix)]

    # Apply filter patterns
    if filters:
        paths = [p for p in paths if matches_filter(p, filters)]

    # Apply ignore patterns
    paths = [p for p in paths if not should_skip_path(p, ignores)]

    # Deduplicate paths (resolve symlinks)
    paths = deduplicate_paths(frame, paths)

    # Test writability
    writability = batch_check_writable(frame, paths)

    # Categorize results
    writable_paths = []
    denied_paths = []

    for path in paths:
        is_writable = writability.get(path, False)
        path_type = check_path_type(frame, path) if is_writable else "unknown"

        if is_writable:
            entry = {"path": path, "type": path_type, "note": None}

            # Check for special files
            if path.startswith("/dev/"):
                entry["type"] = "device"
                entry["note"] = "special file"

            writable_paths.append(entry)
        else:
            # Determine denial reason
            reason = "permission_denied"
            if path.startswith("/System") or (path.startswith("/usr/") and not path.startswith("/usr/local")):
                reason = "sip_protected"
            elif sandbox_active:
                reason = "sandbox_denied"

            denied_paths.append({"path": path, "reason": reason})

    duration = time.time() - start_time
    tested_count = len(paths)
    scan_mode = "quick" if quick else "default"

    # Format output
    if output_json:
        output = format_output_json(
            writable_paths,
            denied_paths,
            platform,
            container,
            temp_dir,
            sandbox_active,
            tested_count,
            duration,
            scan_mode,
        )
    else:
        output = format_output_human(
            writable_paths, denied_paths, platform, container, temp_dir, sandbox_active, tested_count, duration, verbose
        )

    print(output)
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    module_path = f"{__name__}.osbx_command"
    debugger.HandleCommand(
        'command script add -h "Scan sandbox filesystem access. '
        'Usage: osbx [--quick] [--verbose] [--json] [--filter pattern] [path_prefix]" '
        f"-f {module_path} osbx"
    )
    print(f"[lldb-objc v{__version__}] 'osbx' installed - Scan sandbox writable paths")
