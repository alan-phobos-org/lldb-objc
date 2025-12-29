#!/usr/bin/env python3
"""
LLDB script for setting auto-logging breakpoints on Objective-C methods.

Usage:
    owatch -[ClassName selector:]      # Watch instance method
    owatch +[ClassName classMethod:]   # Watch class method
    owatch list                        # List active watches
    owatch clear                       # Remove all watches

Flags:
    --detailed       Multi-line format for each argument
    --stack          Include caller info
    --minimal        Timestamp + method only, no args
    --once           Remove after first hit
    --count=N        Remove after N hits
    --condition="X"  Conditional logging (LLDB expression)

Examples:
    owatch -[NSUserDefaults setObject:forKey:]
    owatch --minimal -[NSString description]
    owatch --once +[NSDate date]
    owatch --count=5 -[UIView layoutSubviews]
    owatch --stack -[IDSService sendMessage:]
"""

from __future__ import annotations

import lldb
import os
import shlex
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Add the script directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

from objc_utils import (
    parse_method_signature,
    resolve_method_address,
    format_method_name,
    get_arch_registers
)

# Type aliases for clarity
WatchInfo = Dict[str, Any]
ProcessWatches = Dict[int, WatchInfo]

# Global state for active watches
# Structure: {process_id: {breakpoint_id: {...watch_info...}}}
_active_watches_by_process: Dict[int, ProcessWatches] = {}


def _get_watches_for_process(process: lldb.SBProcess) -> ProcessWatches:
    """Get the watches dict for a specific process, creating if needed."""
    pid = process.GetProcessID()
    if pid not in _active_watches_by_process:
        _active_watches_by_process[pid] = {}
    return _active_watches_by_process[pid]


def _build_flags_description(info: WatchInfo) -> List[str]:
    """Build a flags description string from watch info dict."""
    flags = []
    if info.get('minimal'):
        flags.append('minimal')
    elif info.get('detailed'):
        flags.append('detailed')
    if info.get('stack'):
        flags.append('stack')
    if info.get('count_limit', 0) > 0:
        flags.append(f"count={info['count_limit']}")
    if info.get('condition'):
        flags.append(f"condition={info['condition']}")
    return flags


def _get_arg_count_from_method(method_name: str) -> int:
    """Extract argument count from method name by counting colons in selector."""
    if ' ' not in method_name:
        return 0
    selector_part = method_name.split(' ', 1)[1].rstrip(']')
    return selector_part.count(':')


def _get_arg_values(
    frame: lldb.SBFrame,
    process: lldb.SBProcess,
    arg_regs: List[str],
    arg_count: int
) -> List[str]:
    """Get formatted argument values from registers."""
    args = []
    for reg_name in arg_regs[:arg_count]:
        val = format_register_value(frame, reg_name, process)
        if val:
            args.append(val)
    return args


def get_timestamp() -> str:
    """Get formatted timestamp for logging."""
    now = datetime.now()
    return now.strftime("[%H:%M:%S.") + f"{now.microsecond // 1000:03d}]"


def get_caller_info(frame: lldb.SBFrame) -> Optional[str]:
    """
    Get caller information from the stack frame.

    Returns:
        String describing the caller, e.g., "-[AppDelegate saveSettings] +0x42"
    """
    thread = frame.GetThread()
    if thread.GetNumFrames() < 2:
        return None

    # Get the caller frame (frame 1, since frame 0 is current)
    caller_frame = thread.GetFrameAtIndex(1)
    if not caller_frame.IsValid():
        return None

    # Get function name
    function = caller_frame.GetFunction()
    if function.IsValid():
        name = function.GetDisplayName()
    else:
        symbol = caller_frame.GetSymbol()
        if symbol.IsValid():
            name = symbol.GetDisplayName()
        else:
            name = "???"

    # Get offset within function
    pc = caller_frame.GetPC()
    start_addr = caller_frame.GetSymbol().GetStartAddress().GetLoadAddress(
        thread.GetProcess().GetTarget()
    ) if caller_frame.GetSymbol().IsValid() else 0

    if start_addr != 0:
        offset = pc - start_addr
        return f"{name} +0x{offset:x}"
    else:
        return name


def format_register_value(
    frame: lldb.SBFrame,
    reg_name: str,
    process: lldb.SBProcess
) -> Optional[str]:
    """
    Format a register value for display.

    Returns:
        String with address and optional description
    """
    reg_value = frame.FindRegister(reg_name)
    if not reg_value.IsValid():
        return None

    addr = reg_value.GetValueAsUnsigned()
    if addr == 0:
        return "nil"

    return f"0x{addr:x}"


def watch_callback(
    frame: lldb.SBFrame,
    bp_loc: lldb.SBBreakpointLocation,
    extra_args: Any,
    internal_dict: Dict[str, Any]
) -> bool:
    """
    Callback function called when a watched method is hit.

    This logs the method call and returns False to continue execution.
    """
    breakpoint = bp_loc.GetBreakpoint()
    bp_id = breakpoint.GetID()
    process = frame.GetThread().GetProcess()
    active_watches = _get_watches_for_process(process)

    if bp_id not in active_watches:
        return False

    watch_info = active_watches[bp_id]
    method_name = watch_info['method_name']
    is_detailed = watch_info.get('detailed', False)
    show_stack = watch_info.get('stack', False)
    is_minimal = watch_info.get('minimal', False)
    count_limit = watch_info.get('count_limit', 0)

    # Increment hit count
    watch_info['hit_count'] = watch_info.get('hit_count', 0) + 1
    hit_count = watch_info['hit_count']

    # Common setup
    timestamp = get_timestamp()
    self_reg, cmd_reg, arg_regs = get_arch_registers(frame)
    arg_count = _get_arg_count_from_method(method_name)

    # Get caller info if needed (used by both --stack modes)
    caller = get_caller_info(frame) if show_stack else None

    if is_minimal:
        # Minimal: timestamp + method name + optional caller
        output = f"\033[90m{timestamp}\033[0m {method_name}"
        if caller:
            output += f" \033[90m<- {caller}\033[0m"
        print(output)
    elif is_detailed:
        # Detailed: multi-line format
        print(f"\033[90m{timestamp}\033[0m {method_name}")

        self_val = format_register_value(frame, self_reg, process)
        if self_val:
            print(f"  \033[90mself:\033[0m {self_val}")

        cmd_val = format_register_value(frame, cmd_reg, process)
        if cmd_val:
            print(f"  \033[90m_cmd:\033[0m {cmd_val}")

        for i, val in enumerate(_get_arg_values(frame, process, arg_regs, arg_count)):
            print(f"  \033[90marg{i}:\033[0m {val}")

        if caller:
            print(f"  \033[90mcaller:\033[0m {caller}")
    else:
        # Default: one line with addresses
        self_val = format_register_value(frame, self_reg, process)
        args = _get_arg_values(frame, process, arg_regs, arg_count)

        output = f"\033[90m{timestamp}\033[0m {method_name}"
        if self_val:
            output += f" \033[90m{self_val}\033[0m"
        if args:
            output += " " + " ".join(args)
        if caller:
            output += f" \033[90m<- {caller}\033[0m"

        print(output)

    # Check if we should remove the breakpoint after N hits
    if count_limit > 0 and hit_count >= count_limit:
        target = process.GetTarget()
        target.BreakpointDelete(bp_id)
        del active_watches[bp_id]
        print(f"\033[90m[owatch: removed after {hit_count} hit(s)]\033[0m")

    return False


def _parse_command_args(command: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Parse command arguments, properly handling quoted strings.

    Returns:
        Tuple of (args_list, error_message)
    """
    # Use shlex to properly handle quoted arguments
    try:
        # shlex.split handles quotes properly
        return shlex.split(command), None
    except ValueError as e:
        return None, f"Invalid command syntax: {e}"


def _parse_flags(
    args: List[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Parse flags from argument list.

    Returns:
        Tuple of (flags_dict, method_signature, error_message)
    """
    flags = {
        'detailed': False,
        'stack': False,
        'minimal': False,
        'count_limit': 0,
        'condition': None
    }
    method_signature = None

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == '--detailed':
            flags['detailed'] = True
        elif arg == '--stack':
            flags['stack'] = True
        elif arg == '--minimal':
            flags['minimal'] = True
        elif arg == '--once':
            flags['count_limit'] = 1
        elif arg.startswith('--count='):
            try:
                flags['count_limit'] = int(arg.split('=')[1])
                if flags['count_limit'] < 1:
                    return None, None, "--count value must be a positive integer (got: {})".format(flags['count_limit'])
            except ValueError:
                return None, None, "Invalid --count value: must be an integer"
        elif arg == '--count' and i + 1 < len(args):
            try:
                flags['count_limit'] = int(args[i + 1])
                if flags['count_limit'] < 1:
                    return None, None, "--count value must be a positive integer (got: {})".format(flags['count_limit'])
                i += 1
            except ValueError:
                return None, None, "Invalid --count value: must be an integer"
        elif arg.startswith('--condition='):
            flags['condition'] = arg.split('=', 1)[1]
        elif arg == '--condition' and i + 1 < len(args):
            flags['condition'] = args[i + 1]
            i += 1
        elif arg.startswith('-[') or arg.startswith('+['):
            # Method signature - collect remaining args
            method_signature = ' '.join(args[i:])
            break
        elif arg.startswith('--'):
            return None, None, f"Unknown flag: {arg}"

        i += 1

    return flags, method_signature, None


def watch_objc_method(
    debugger: lldb.SBDebugger,
    command: str,
    result: lldb.SBCommandReturnObject,
    internal_dict: Dict[str, Any]
) -> None:
    """
    Set an auto-logging breakpoint on an Objective-C method.
    Logs method calls without stopping execution.
    """
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    if not process.IsValid() or process.GetState() != lldb.eStateStopped:
        result.SetError("Process must be running and stopped")
        return

    # Parse command with proper quote handling
    args, error = _parse_command_args(command)
    if error:
        result.SetError(error)
        return

    if not args:
        result.SetError("Usage: owatch [-flags] -[ClassName selector:] or owatch list/clear")
        return

    # Handle subcommands
    if args[0] == 'list':
        list_watches(process, result)
        return
    elif args[0] == 'clear':
        clear_watches(target, process, result)
        return

    # Parse flags
    flags, method_signature, error = _parse_flags(args)
    if error:
        result.SetError(error)
        return

    if not method_signature:
        result.SetError("No method signature provided")
        return

    # Parse the method signature
    is_instance_method, class_name, selector, error = parse_method_signature(method_signature)
    if error:
        result.SetError(error)
        return

    # Get the current frame
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # Resolve the method address
    method_name = format_method_name(class_name, selector, is_instance_method)

    print(f"Resolving {method_name}...")

    imp_addr, _, _, error = resolve_method_address(frame, class_name, selector, is_instance_method)
    if error:
        result.SetError(error)
        return

    # Create the breakpoint
    breakpoint = target.BreakpointCreateByAddress(imp_addr)

    if not breakpoint.IsValid():
        result.SetError(f"Failed to create breakpoint at 0x{imp_addr:x}")
        return

    # Configure the breakpoint
    breakpoint.SetAutoContinue(True)
    breakpoint.AddName(f"owatch:{method_name}")

    # Set condition if provided
    if flags['condition']:
        breakpoint.SetCondition(flags['condition'])

    # Set up the callback
    # Use SetScriptCallbackBody to embed the callback directly
    # This avoids module name resolution issues
    callback_body = """
import objc_watch
return objc_watch.watch_callback(frame, bp_loc, extra_args, internal_dict)
"""

    error = lldb.SBError()
    success = breakpoint.SetScriptCallbackBody(callback_body)

    if not success:
        target.BreakpointDelete(breakpoint.GetID())
        result.SetError(f"Failed to set callback for breakpoint at 0x{imp_addr:x}")
        return

    # Store watch info in process-scoped state
    bp_id = breakpoint.GetID()
    active_watches = _get_watches_for_process(process)
    active_watches[bp_id] = {
        'method_name': method_name,
        'detailed': flags['detailed'],
        'stack': flags['stack'],
        'minimal': flags['minimal'],
        'count_limit': flags['count_limit'],
        'hit_count': 0,
        'condition': flags['condition'],
        'imp_addr': imp_addr
    }

    # Print confirmation
    print(f"Watching {method_name}")
    print(f"  \033[90mBreakpoint #{bp_id} at 0x{imp_addr:x}\033[0m")

    flags_desc = _build_flags_description(active_watches[bp_id])
    if flags_desc:
        print(f"  \033[90mFlags: {', '.join(flags_desc)}\033[0m")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def list_watches(process: lldb.SBProcess, result: lldb.SBCommandReturnObject) -> None:
    """List all active watches for the current process."""
    active_watches = _get_watches_for_process(process)

    if not active_watches:
        print("No active watches")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    print(f"Active watches ({len(active_watches)}):")
    for bp_id, info in active_watches.items():
        method_name = info['method_name']
        hit_count = info.get('hit_count', 0)

        flags = _build_flags_description(info)
        flags_str = f" \033[90m({', '.join(flags)})\033[0m" if flags else ""
        hits_str = f" \033[90m[{hit_count} hit(s)]\033[0m"

        print(f"  #{bp_id}: {method_name}{flags_str}{hits_str}")

    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def clear_watches(
    target: lldb.SBTarget,
    process: lldb.SBProcess,
    result: lldb.SBCommandReturnObject
) -> None:
    """Remove all active watches for the current process."""
    active_watches = _get_watches_for_process(process)

    if not active_watches:
        print("No active watches to clear")
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
        return

    count = len(active_watches)

    # Delete all watched breakpoints
    for bp_id in list(active_watches.keys()):
        target.BreakpointDelete(bp_id)

    active_watches.clear()

    print(f"Cleared {count} watch(es)")
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)


def __lldb_init_module(debugger: lldb.SBDebugger, internal_dict: Dict[str, Any]) -> None:
    """Initialize the module by registering the command."""
    debugger.HandleCommand(
        'command script add -h "Watch Objective-C methods with auto-logging breakpoints. '
        'Usage: owatch -[ClassName selector:] [--detailed|--minimal|--stack|--once|--count=N|--condition=X] or owatch list|clear" '
        '-f objc_watch.watch_objc_method owatch'
    )
    print(f"[lldb-objc v{__version__}] Objective-C method watcher 'owatch' has been installed.")
    print("Usage: owatch -[ClassName selector:]")
    print("       owatch +[ClassName classMethod:]")
    print("       owatch list | clear")
