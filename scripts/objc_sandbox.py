#!/usr/bin/env python3
"""
LLDB script for scanning sandbox filesystem access - osbx command.

Efficiently scans the filesystem to determine which paths are writable
from within the currently debugged process's sandbox.

Usage:
    osbx [options] [path_prefix]

Options:
    --quick, -q       Test only most common paths (~20 paths)
    --thorough, -t    Deep scan with subdirectory enumeration (depth-limited)
    --verbose, -v     Show all paths tested, not just writable ones
    --json            Output in JSON format for scripting
    --filter PATTERN  Only test paths matching glob/regex pattern
    --ignore PATTERN  Skip paths matching glob/regex pattern
    --no-default-ignore  Don't apply default ignore patterns
    --output FILE     Write results to file instead of stdout
    --log FILE        Write detailed per-path check log (TSV format)
    --max-paths N     Stop after testing N paths (default: 500, thorough: 10000)
    --max-depth N     Maximum directory depth for --thorough (default: 3)
    --no-progress     Disable progress indicator

Arguments:
    path_prefix       Only test paths starting with this prefix (e.g., /var)

Examples:
    osbx                      # Quick scan of interesting paths
    osbx --quick              # Fastest scan (~20 paths)
    osbx --thorough           # Deep scan with subdirectory enumeration
    osbx /var                 # Only test paths under /var
    osbx --filter "/tmp/**"   # Only test paths under /tmp
    osbx --json               # JSON output for scripting
    osbx --output writable.txt --json  # Save JSON results to file
    osbx --log scan.log       # Save detailed scan log for debugging

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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add the script directory to path for version import
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Guard against double initialization
_initialized = False

# Try to import lldb - may not be available during unit tests
try:
    import lldb
    from objc_utils import evaluate_expression
except ImportError:
    lldb = None
    evaluate_expression = None

# Batch size for testing writability (consistent with ocls)
DEFAULT_BATCH_SIZE = 35

# Safety limits
DEFAULT_MAX_PATHS = 500
THOROUGH_MAX_PATHS = 10000
DEFAULT_MAX_DEPTH = 2
THOROUGH_MAX_DEPTH = 3
MAX_ENTRIES_PER_DIR = 100  # Limit directory enumeration

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
        filters: List of glob or regex patterns (supports ** for recursive matching)

    Returns:
        True if path matches any filter (or if filters is empty)
    """
    if not filters:
        return True  # No filter = match all

    for pattern in filters:
        # Handle ** recursive glob by converting to regex
        if "**" in pattern:
            # Convert glob pattern to regex: ** matches any path segments
            # Use placeholder to avoid * in .* being re-converted
            regex_pattern = pattern.replace(".", r"\.")
            regex_pattern = regex_pattern.replace("**", "\x00STARSTAR\x00")
            regex_pattern = regex_pattern.replace("*", "[^/]*")
            regex_pattern = regex_pattern.replace("\x00STARSTAR\x00", ".*")
            regex_pattern = "^" + regex_pattern + "$"
            try:
                if re.match(regex_pattern, path):
                    return True
            except re.error:
                pass
        else:
            # Try standard fnmatch glob
            if fnmatch.fnmatch(path, pattern):
                return True
        # Try as regex pattern
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
        ignore_patterns: List of glob or regex patterns to ignore (supports **)

    Returns:
        True if path should be skipped
    """
    for pattern in ignore_patterns:
        # Handle ** recursive glob by converting to regex
        if "**" in pattern:
            # Use placeholder to avoid * in .* being re-converted
            regex_pattern = pattern.replace(".", r"\.")
            regex_pattern = regex_pattern.replace("**", "\x00STARSTAR\x00")
            regex_pattern = regex_pattern.replace("*", "[^/]*")
            regex_pattern = regex_pattern.replace("\x00STARSTAR\x00", ".*")
            try:
                if re.search(regex_pattern, path):
                    return True
            except re.error:
                pass
        else:
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
    interrupted: bool = False,
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
        "interrupted": interrupted,
    }
    return json.dumps(data, indent=2)


class ScanLogger:
    """Writes detailed per-path check log in TSV format."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.entries: List[Dict[str, str]] = []
        self.start_time = time.time()

    def log_check(
        self,
        path: str,
        result: str,
        path_type: str,
        reason: str,
        details: str = "-",
    ) -> None:
        """
        Record a single path check result.

        Args:
            path: The path that was checked
            result: "writable", "not_writable", "skipped", "error"
            path_type: "directory", "file", "device", "symlink", "unknown"
            reason: Human-readable reason (e.g., "sandbox_denied", "-")
            details: Additional details (e.g., error code, symlink target)
        """
        self.entries.append(
            {
                "path": path,
                "result": result,
                "type": path_type,
                "reason": reason,
                "details": details,
            }
        )

    def write(self, metadata: Dict[str, Any]) -> None:
        """Write log file with header and entries."""
        with open(self.log_path, "w") as f:
            # Header
            f.write(f"# osbx scan log - {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}\n")
            f.write(f"# Platform: {metadata.get('platform', 'unknown')}")
            if metadata.get("container"):
                f.write(f", Container: {metadata['container']}")
            f.write("\n")
            if metadata.get("filter"):
                f.write(f"# Filter: {metadata['filter']}\n")
            duration = time.time() - self.start_time
            writable = sum(1 for e in self.entries if e["result"] == "writable")
            f.write(f"# Paths tested: {len(self.entries)}, Writable: {writable}, Duration: {duration:.2f}s\n")
            f.write("PATH\tRESULT\tTYPE\tREASON\tDETAILS\n")

            # Entries
            for entry in self.entries:
                f.write(f"{entry['path']}\t{entry['result']}\t{entry['type']}\t{entry['reason']}\t{entry['details']}\n")


def format_progress(
    current: int,
    total: int,
    writable_count: int,
    start_time: float,
) -> str:
    """
    Format a progress indicator string.

    Args:
        current: Current path count
        total: Total paths to scan
        writable_count: Number of writable paths found so far
        start_time: Scan start time

    Returns:
        Progress string like "Scanning... [=====>    ] 45% - 12 writable"
    """
    if total <= 0:
        return "Scanning..."

    pct = min(100, int(100 * current / total))
    bar_width = 20
    filled = int(bar_width * current / total)
    bar = "=" * filled + ">" + " " * (bar_width - filled - 1)

    elapsed = time.time() - start_time
    if current > 0 and pct < 100:
        eta = (elapsed / current) * (total - current)
        eta_str = f" - ETA: {eta:.0f}s"
    else:
        eta_str = ""

    return f"Scanning... [{bar}] {current}/{total} ({pct}%) - {writable_count} writable{eta_str}"


# ============================================================================
# LLDB-Dependent Functions
# ============================================================================


def get_container_path(frame) -> Optional[str]:
    """Get the app's sandbox container path using NSHomeDirectory()."""
    if not lldb:
        return None

    expr = "(NSString *)NSHomeDirectory()"
    result = evaluate_expression(frame, expr)
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
    result = evaluate_expression(frame, expr)
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
    result = evaluate_expression(frame, expr)
    if result.GetValueAsUnsigned() == 1:
        return "iOS"

    return "macOS"  # Default to macOS


def is_sandboxed(frame) -> bool:
    """
    Check if process is running under sandbox.

    Detects both App Sandbox (via container path) and sandbox_init() sandboxes
    (by checking if write access to home directory is denied).

    Returns:
        True if sandboxed
    """
    if not lldb:
        return False

    # Method 1: Check for sandbox container path pattern (App Sandbox)
    home = get_container_path(frame)
    if home:
        if "/Library/Containers/" in home:
            return True
        if "/var/mobile/Containers/" in home:
            return True

    # Method 2: Check if write access to home directory is denied
    # A non-sandboxed process should have write access to its home directory
    # If access() returns -1, the sandbox is restricting access
    # Note: access() works correctly from LLDB unlike sandbox_check()
    if home:
        escaped_home = escape_objc_string(home)
        expr = f'(int)access("{escaped_home}", 2)'  # W_OK = 2
        result = evaluate_expression(frame, expr)
        if result.GetError().Success():
            # -1 means access denied (sandboxed)
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

    result = evaluate_expression(frame, expr)
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
    Check writability of multiple paths using access() system call.

    Uses access(path, W_OK) which properly respects sandbox_init() restrictions,
    unlike NSFileManager's isWritableFileAtPath: which only checks Unix perms,
    and unlike sandbox_check() which doesn't work reliably from LLDB expressions.

    Args:
        frame: LLDB SBFrame
        paths: List of paths to check
        batch_size: Number of paths per batch

    Returns:
        Dict mapping path -> is_writable (True if writable)
    """
    if not lldb:
        return {}

    results = {}

    for i in range(0, len(paths), batch_size):
        batch = paths[i : i + batch_size]

        # Escape paths for Objective-C string literals
        escaped_paths = [escape_objc_string(p) for p in batch]
        path_array = ", ".join(f'@"{p}"' for p in escaped_paths)

        # Use access() with W_OK (2) to check write permission
        # access() properly respects sandbox restrictions from LLDB expressions
        # Returns 0 if access is allowed, -1 if denied
        # Note: Use index-based iteration (for-in doesn't work in LLDB blocks)
        # Note: access() must be cast to (int) inside LLDB block expressions
        expr = f"""
        (NSArray *)^{{
            NSArray *paths = @[{path_array}];
            NSMutableArray *results = [NSMutableArray array];
            for (NSUInteger i = 0; i < [paths count]; i++) {{
                NSString *path = paths[i];
                // W_OK = 2 (check for write permission)
                // Must cast access() return type for LLDB
                int result = (int)access([path UTF8String], 2);
                // access returns 0 if allowed
                [results addObject:@(result == 0)];
            }}
            return results;
        }}()
        """

        result = evaluate_expression(frame, expr)
        if result.GetError().Success():
            # Parse NSArray of NSNumber(BOOL) results
            # Note: NSNumber bool values must be read via GetSummary() which returns "YES"/"NO"
            # GetValueAsUnsigned() returns the NSNumber pointer address, not the bool value
            count = result.GetNumChildren()
            for j in range(min(count, len(batch))):
                child = result.GetChildAtIndex(j)
                summary = child.GetSummary()
                # Summary is "YES" or "NO" for NSNumber booleans
                is_writable = summary == "YES"
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
    result = evaluate_expression(frame, expr)
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


def enumerate_directory(
    frame,
    path: str,
    max_entries: int = MAX_ENTRIES_PER_DIR,
) -> Tuple[List[str], Optional[int]]:
    """
    Enumerate contents of a directory (shallow).

    Args:
        frame: LLDB SBFrame
        path: Directory path to enumerate
        max_entries: Maximum entries to return

    Returns:
        Tuple of (list of full paths, error_code or None)
    """
    if not lldb:
        return [], -1

    escaped_path = escape_objc_string(path)

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

    result = evaluate_expression(frame, expr)
    if not result.GetError().Success():
        return [], -1

    # Check for error in result
    num_children = result.GetNumChildren()
    for i in range(num_children):
        child = result.GetChildAtIndex(i)
        name = child.GetName()
        if name == "error":
            error_val = child.GetChildAtIndex(0)
            if error_val.IsValid():
                return [], error_val.GetValueAsSigned()

    # Extract paths
    paths = []
    for i in range(num_children):
        child = result.GetChildAtIndex(i)
        name = child.GetName()
        if name == "paths":
            paths_array = child.GetChildAtIndex(0)
            if paths_array.IsValid():
                for j in range(paths_array.GetNumChildren()):
                    path_child = paths_array.GetChildAtIndex(j)
                    summary = path_child.GetSummary()
                    if summary:
                        paths.append(summary.strip('"@'))

    return paths, None


def expand_paths_thorough(
    frame,
    base_paths: List[str],
    ignore_patterns: List[str],
    max_depth: int,
    max_paths: int,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """
    Expand base paths by enumerating subdirectories of writable directories.

    Args:
        frame: LLDB SBFrame
        base_paths: Initial list of paths to test
        ignore_patterns: Patterns to skip
        max_depth: Maximum recursion depth
        max_paths: Maximum total paths to return
        progress_callback: Optional callback for progress updates

    Returns:
        Expanded list of paths to test
    """
    all_paths = list(base_paths)
    seen = set(base_paths)
    to_expand = [(p, 0) for p in base_paths]  # (path, current_depth)

    while to_expand and len(all_paths) < max_paths:
        path, depth = to_expand.pop(0)

        if depth >= max_depth:
            continue

        if progress_callback:
            progress_callback(f"Enumerating: {path}")

        # Check if directory is readable first
        path_type = check_path_type(frame, path)
        if path_type != "directory":
            continue

        # Enumerate directory contents
        contents, error = enumerate_directory(frame, path)
        if error is not None:
            continue

        for child_path in contents:
            if child_path in seen:
                continue
            if should_skip_path(child_path, ignore_patterns):
                continue

            seen.add(child_path)
            all_paths.append(child_path)

            if len(all_paths) >= max_paths:
                break

            # Queue directories for further expansion
            child_type = check_path_type(frame, child_path)
            if child_type == "directory":
                to_expand.append((child_path, depth + 1))

    return all_paths[:max_paths]


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

    # Handle help flag
    if "--help" in args or "-h" in args:
        help_text = """osbx - Scan sandbox filesystem access

Usage: osbx [options] [path_prefix]

Options:
    --quick, -q       Test only most common paths (~10 paths)
    --thorough, -t    Deep scan with subdirectory enumeration
    --verbose, -v     Show all paths tested, not just writable ones
    --json            Output in JSON format for scripting
    --filter PATTERN  Only test paths matching glob/regex pattern
    --ignore PATTERN  Skip paths matching glob/regex pattern
    --no-default-ignore  Don't apply default ignore patterns
    --output FILE     Write results to file instead of stdout
    --log FILE        Write detailed per-path check log (TSV format)
    --max-paths N     Stop after testing N paths (default: 500)
    --max-depth N     Maximum directory depth for --thorough (default: 2)
    --no-progress     Disable progress indicator

Arguments:
    path_prefix       Only test paths starting with this prefix

Examples:
    osbx                      # Default scan of interesting paths
    osbx --quick              # Fastest scan (~10 paths)
    osbx --thorough           # Deep scan with subdirectory enumeration
    osbx /var                 # Only test paths under /var
    osbx --filter "/tmp/**"   # Only test paths under /tmp
    osbx --json               # JSON output for scripting
"""
        print(help_text)
        return

    quick = "--quick" in args or "-q" in args
    thorough = "--thorough" in args or "-t" in args
    verbose = "--verbose" in args or "-v" in args
    output_json = "--json" in args
    no_default_ignore = "--no-default-ignore" in args
    no_progress = "--no-progress" in args

    # Parse --filter, --ignore, --output, --log, --max-paths, --max-depth options
    filters = []
    ignores = [] if no_default_ignore else DEFAULT_IGNORE_PATTERNS.copy()
    path_prefix = None
    output_file = None
    log_file = None
    max_paths = THOROUGH_MAX_PATHS if thorough else DEFAULT_MAX_PATHS
    max_depth = THOROUGH_MAX_DEPTH if thorough else DEFAULT_MAX_DEPTH

    def strip_quotes(s: str) -> str:
        """Strip surrounding quotes from a string."""
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        return s

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--filter" and i + 1 < len(args):
            filters.append(strip_quotes(args[i + 1]))
            i += 1
        elif arg.startswith("--filter="):
            filters.append(strip_quotes(arg.split("=", 1)[1]))
        elif arg == "--ignore" and i + 1 < len(args):
            ignores.append(strip_quotes(args[i + 1]))
            i += 1
        elif arg.startswith("--ignore="):
            ignores.append(strip_quotes(arg.split("=", 1)[1]))
        elif arg == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 1
        elif arg.startswith("--output="):
            output_file = arg.split("=", 1)[1]
        elif arg == "--log" and i + 1 < len(args):
            log_file = args[i + 1]
            i += 1
        elif arg.startswith("--log="):
            log_file = arg.split("=", 1)[1]
        elif arg == "--max-paths" and i + 1 < len(args):
            try:
                max_paths = int(args[i + 1])
            except ValueError:
                pass
            i += 1
        elif arg.startswith("--max-paths="):
            try:
                max_paths = int(arg.split("=", 1)[1])
            except ValueError:
                pass
        elif arg == "--max-depth" and i + 1 < len(args):
            try:
                max_depth = int(args[i + 1])
            except ValueError:
                pass
            i += 1
        elif arg.startswith("--max-depth="):
            try:
                max_depth = int(arg.split("=", 1)[1])
            except ValueError:
                pass
        elif not arg.startswith("-") and not path_prefix:
            path_prefix = strip_quotes(arg)
        i += 1

    # Quick mode overrides thorough
    if quick:
        thorough = False
        max_paths = 50  # Quick mode has lower limit

    # Initialize logger if requested
    logger = ScanLogger(log_file) if log_file else None

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

    # Thorough mode: expand paths by enumerating subdirectories
    if thorough:

        def progress_cb(msg: str) -> None:
            if not no_progress:
                print(f"\r{msg:<60}", end="", flush=True)

        paths = expand_paths_thorough(
            frame,
            paths,
            ignores,
            max_depth=max_depth,
            max_paths=max_paths,
            progress_callback=progress_cb if not no_progress else None,
        )
        if not no_progress:
            print("\r" + " " * 60 + "\r", end="")  # Clear progress line

    # Apply max_paths limit
    paths = paths[:max_paths]

    # Test writability with progress
    writable_paths = []
    denied_paths = []
    last_progress_time = time.time()

    # Process paths in batches for writability check
    writability = {}
    total_paths = len(paths)

    for batch_start in range(0, total_paths, DEFAULT_BATCH_SIZE):
        batch_end = min(batch_start + DEFAULT_BATCH_SIZE, total_paths)
        batch = paths[batch_start:batch_end]

        batch_results = batch_check_writable(frame, batch)
        writability.update(batch_results)

        # Show progress periodically
        now = time.time()
        if not no_progress and (now - last_progress_time >= 0.5 or batch_end == total_paths):
            writable_so_far = sum(1 for p in list(writability.keys()) if writability.get(p))
            progress_str = format_progress(batch_end, total_paths, writable_so_far, start_time)
            print(f"\r{progress_str:<70}", end="", flush=True)
            last_progress_time = now

    # Clear progress line
    if not no_progress and total_paths > 0:
        print("\r" + " " * 70 + "\r", end="")

    # Categorize results
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

            if logger:
                logger.log_check(path, "writable", path_type, "-")
        else:
            # Determine denial reason
            reason = "permission_denied"
            if path.startswith("/System") or (path.startswith("/usr/") and not path.startswith("/usr/local")):
                reason = "sip_protected"
            elif sandbox_active:
                reason = "sandbox_denied"

            denied_paths.append({"path": path, "reason": reason})

            if logger:
                logger.log_check(path, "not_writable", path_type, reason)

    duration = time.time() - start_time
    tested_count = len(paths)

    if quick:
        scan_mode = "quick"
    elif thorough:
        scan_mode = "thorough"
    else:
        scan_mode = "default"

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
            writable_paths,
            denied_paths,
            platform,
            container,
            temp_dir,
            sandbox_active,
            tested_count,
            duration,
            verbose,
        )

    # Write output to file or print
    if output_file:
        try:
            with open(output_file, "w") as f:
                f.write(output)
            print(f"Results written to: {output_file}")
        except IOError as e:
            print(f"Error writing to {output_file}: {e}")
            print(output)
    else:
        print(output)

    # Write log file if requested
    if logger:
        try:
            logger.write(
                {
                    "platform": platform,
                    "container": container,
                    "filter": ", ".join(filters) if filters else None,
                }
            )
            print(f"Scan log written to: {log_file}")
        except IOError as e:
            print(f"Error writing log to {log_file}: {e}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    module_path = f"{__name__}.osbx_command"
    debugger.HandleCommand(
        'command script add -h "Scan sandbox filesystem access. '
        "Usage: osbx [--quick|-q] [--thorough|-t] [--verbose|-v] [--json] "
        '[--filter PATTERN] [--output FILE] [--log FILE] [path_prefix]" '
        f"-f {module_path} osbx"
    )
    print(f"[lldb-objc v{__version__}] 'osbx' installed - Scan sandbox writable paths")
