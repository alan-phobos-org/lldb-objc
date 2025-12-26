#!/bin/bash
# Bootstrap script to launch LLDB with testing environment for objc_breakpoint

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HELLO_WORLD_PATH="$SCRIPT_DIR/HelloWorld/HelloWorld/HelloWorld"
OBJC_BREAKPOINT_PATH="$SCRIPT_DIR/objc_breakpoint.py"

# Verify paths
if [ ! -f "$HELLO_WORLD_PATH" ]; then
    echo "Error: HelloWorld binary not found at: $HELLO_WORLD_PATH"
    exit 1
fi

if [ ! -f "$OBJC_BREAKPOINT_PATH" ]; then
    echo "Error: objc_breakpoint.py not found at: $OBJC_BREAKPOINT_PATH"
    exit 1
fi

echo "Launching LLDB with HelloWorld binary..."
echo "Binary path: $HELLO_WORLD_PATH"
echo "Script path: $OBJC_BREAKPOINT_PATH"
echo

# Create temporary LLDB command file
TEMP_FILE=$(mktemp /tmp/lldb_commands.XXXXXX)

cat > "$TEMP_FILE" << EOF
# Load the target binary
file $HELLO_WORLD_PATH

# Set breakpoint on main
b main

# Run the process
run

# Load IDS.framework (this will load the Objective-C runtime and IDS private classes)
expr (void)dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", 0x2)

# Import the objc_breakpoint script
command script import $OBJC_BREAKPOINT_PATH

# Display help
script print("\\n=== Ready for testing! ===\\n")
script print("Available commands:\\n")
script print("  obrk -[ClassName selector:]  - Set breakpoint on instance method")
script print("  obrk +[ClassName selector:]  - Set breakpoint on class method\\n")
script print("Example: obrk -[IDSService init]\\n")
EOF

# Launch LLDB with the command file
lldb -s "$TEMP_FILE"

# Clean up
rm "$TEMP_FILE"
