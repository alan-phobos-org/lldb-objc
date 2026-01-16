#!/usr/bin/env python3
"""
LLDB Objective-C Tools - Directory-based loader with reload support.

This module loads all LLDB Objective-C debugging commands and provides
a reload mechanism for updating commands within an active LLDB session.

Usage in .lldbinit:
    command script import /path/to/lldb-objc

To reload commands within an LLDB session:
    oreload
"""

from __future__ import annotations

import importlib
import lldb
import os
import sys
from typing import Dict, Any

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Command modules to load (with package prefix)
COMMAND_MODULES = [
    ".objc_breakpoint",
    ".objc_sel",
    ".objc_cls",
    ".objc_call",
    ".objc_watch",
    ".objc_protos",
    ".objc_pool",
    ".objc_instance",
    ".objc_explain",
    ".objc_decompile",
    ".objc_sandbox",
]

# Track loaded modules for reloading
_loaded_modules = {}
# Track which modules have been initialized (prevents double init)
_initialized_modules = set()


def _load_command_module(module_name: str, debugger: lldb.SBDebugger, force_reload: bool = False) -> bool:
    """Load or reload a single command module."""
    global _loaded_modules, _initialized_modules

    try:
        # Import or reload the module (relative import from scripts package)
        if module_name in _loaded_modules:
            module = importlib.reload(_loaded_modules[module_name])
            # On reload, we need to re-initialize
            _initialized_modules.discard(module_name)
        else:
            module = importlib.import_module(module_name, package=__name__)
            _loaded_modules[module_name] = module

        # Call the module's initialization function if not already done
        if hasattr(module, "__lldb_init_module"):
            if module_name not in _initialized_modules or force_reload:
                module.__lldb_init_module(debugger, {})
                _initialized_modules.add(module_name)

        return True
    except Exception as e:
        print(f"Error loading {module_name}: {e}", file=sys.stderr)
        return False


def reload_commands(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any],
) -> None:
    """
    Reload all LLDB Objective-C command modules.

    This allows you to update commands without restarting LLDB.
    """
    print(f"Reloading LLDB Objective-C Tools v{__version__}...")

    # Reload utils first (other modules depend on it)
    try:
        if "scripts.objc_utils" in sys.modules:
            importlib.reload(sys.modules["scripts.objc_utils"])
        elif "objc_utils" in sys.modules:
            importlib.reload(sys.modules["objc_utils"])
    except Exception as e:
        print(f"Error reloading objc_utils: {e}", file=sys.stderr)

    # Reload version
    try:
        if "scripts.version" in sys.modules:
            importlib.reload(sys.modules["scripts.version"])
            from .version import __version__ as new_version

            print(f"Version: {new_version}")
        elif "version" in sys.modules:
            importlib.reload(sys.modules["version"])
            from version import __version__ as new_version

            print(f"Version: {new_version}")
    except Exception as e:
        print(f"Error reloading version: {e}", file=sys.stderr)

    # Reload each command module
    success_count = 0
    for module_name in COMMAND_MODULES:
        if _load_command_module(module_name, debugger):
            success_count += 1

    print(f"Reloaded {success_count}/{len(COMMAND_MODULES)} command modules")

    if success_count == len(COMMAND_MODULES):
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
    else:
        result.SetStatus(lldb.eReturnStatusFailed)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """
    Initialize all LLDB Objective-C commands.

    This function is automatically called by LLDB when importing this package.
    """
    print(f"Loading LLDB Objective-C Tools v{__version__}...")

    # Load each command module
    for module_name in COMMAND_MODULES:
        _load_command_module(module_name, debugger)

    # Register the reload command
    # Use the full module path for the reload function
    module_path = f"{__name__}.reload_commands"
    debugger.HandleCommand(
        f'command script add -f {module_path} oreload -h "Reload all LLDB Objective-C command modules"'
    )

    print("LLDB Objective-C Tools loaded. Use 'oreload' to reload commands.")
