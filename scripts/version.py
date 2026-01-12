#!/usr/bin/env python3
"""Version information for LLDB Objective-C Tools."""

import subprocess
from pathlib import Path

# Fallback version (used when not in git repo, e.g., packaged release)
_FALLBACK_VERSION = "1.1.0"


def _get_git_version():
    """Get version from git tags."""
    try:
        # Get the directory containing this file
        script_dir = Path(__file__).parent
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # Strip leading 'v' if present (e.g., v1.1.0 -> 1.1.0)
            if version.startswith("v"):
                version = version[1:]
            return version
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    return None


def get_version():
    """Get the current version, preferring git if available."""
    git_version = _get_git_version()
    return git_version if git_version else _FALLBACK_VERSION


__version__ = get_version()
__author__ = "Alan"
__description__ = "LLDB commands for Objective-C method introspection and debugging"
