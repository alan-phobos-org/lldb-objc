#!/bin/bash
#
# sign-with-entitlements.sh - Sign osbx-standalone with target app's entitlements
#
# This script extracts entitlements from a target application and signs
# osbx-standalone with the same entitlements, allowing it to run under
# an equivalent sandbox configuration.
#
# Usage:
#   ./sign-with-entitlements.sh /path/to/Target.app [signing-identity]
#
# Arguments:
#   /path/to/Target.app   Path to the target application bundle
#   signing-identity      Optional: Code signing identity (default: ad-hoc "-")
#
# Examples:
#   # Sign with ad-hoc identity (for local testing)
#   ./sign-with-entitlements.sh /Applications/Safari.app
#
#   # Sign with Developer ID
#   ./sign-with-entitlements.sh /Applications/MyApp.app "Developer ID Application: My Name"
#
# Notes:
#   - Ad-hoc signing works for local testing but won't run on other machines
#   - To distribute, you need a valid Developer ID certificate
#   - The target app must be signed for entitlements to be extractable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="$SCRIPT_DIR/osbx-standalone"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 /path/to/Target.app [signing-identity]"
    echo ""
    echo "Sign osbx-standalone with the same entitlements as the target app."
    echo ""
    echo "Arguments:"
    echo "  /path/to/Target.app   Path to the target application bundle"
    echo "  signing-identity      Optional: Code signing identity (default: ad-hoc)"
    echo ""
    echo "Examples:"
    echo "  $0 /Applications/Safari.app"
    echo "  $0 /Applications/MyApp.app \"Developer ID Application: My Name\""
    exit 1
}

# Check arguments
if [ $# -lt 1 ]; then
    usage
fi

TARGET_APP="$1"
SIGNING_IDENTITY="${2:--}" # Default to ad-hoc signing

# Validate target app exists
if [ ! -d "$TARGET_APP" ]; then
    echo -e "${RED}Error: Target app not found: $TARGET_APP${NC}"
    exit 1
fi

# Find the main executable in the app bundle
if [ -d "$TARGET_APP/Contents/MacOS" ]; then
    # macOS app bundle
    APP_NAME=$(basename "$TARGET_APP" .app)
    TARGET_BINARY="$TARGET_APP/Contents/MacOS/$APP_NAME"

    # Try to find the actual binary from Info.plist
    if [ -f "$TARGET_APP/Contents/Info.plist" ]; then
        PLIST_EXEC=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$TARGET_APP/Contents/Info.plist" 2>/dev/null || true)
        if [ -n "$PLIST_EXEC" ]; then
            TARGET_BINARY="$TARGET_APP/Contents/MacOS/$PLIST_EXEC"
        fi
    fi
else
    echo -e "${RED}Error: Invalid app bundle structure${NC}"
    exit 1
fi

if [ ! -f "$TARGET_BINARY" ]; then
    echo -e "${RED}Error: Could not find executable in app bundle${NC}"
    echo "Expected: $TARGET_BINARY"
    exit 1
fi

# Check if osbx-standalone binary exists
if [ ! -f "$BINARY" ]; then
    echo -e "${YELLOW}Binary not found. Building osbx-standalone...${NC}"
    make -C "$SCRIPT_DIR" || {
        echo -e "${RED}Error: Failed to build osbx-standalone${NC}"
        exit 1
    }
fi

# Create temp file for entitlements
ENTITLEMENTS_FILE=$(mktemp /tmp/entitlements.XXXXXX.plist)
trap "rm -f $ENTITLEMENTS_FILE" EXIT

echo -e "${GREEN}Extracting entitlements from:${NC} $TARGET_BINARY"

# Extract entitlements
if ! codesign -d --entitlements - "$TARGET_BINARY" > "$ENTITLEMENTS_FILE" 2>/dev/null; then
    echo -e "${YELLOW}Warning: Could not extract entitlements (app may not be sandboxed)${NC}"
    echo -e "${YELLOW}Creating empty entitlements file...${NC}"
    cat > "$ENTITLEMENTS_FILE" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
</dict>
</plist>
EOF
fi

# Check if entitlements file has content
if [ ! -s "$ENTITLEMENTS_FILE" ]; then
    echo -e "${YELLOW}Warning: No entitlements found in target app${NC}"
    cat > "$ENTITLEMENTS_FILE" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
</dict>
</plist>
EOF
fi

# Show extracted entitlements
echo -e "${GREEN}Entitlements:${NC}"
cat "$ENTITLEMENTS_FILE" | grep -v "^Executable" | head -50
echo ""

# Check for sandbox entitlement
if grep -q "com.apple.security.app-sandbox" "$ENTITLEMENTS_FILE"; then
    echo -e "${GREEN}Target app is sandboxed${NC}"
else
    echo -e "${YELLOW}Warning: Target app does not have sandbox entitlement${NC}"
    echo "The scanner will run without sandbox restrictions."
fi

# Sign the binary
echo -e "${GREEN}Signing osbx-standalone with identity:${NC} $SIGNING_IDENTITY"

# Remove existing signature first
codesign --remove-signature "$BINARY" 2>/dev/null || true

# Sign with entitlements
if codesign -s "$SIGNING_IDENTITY" --entitlements "$ENTITLEMENTS_FILE" --force "$BINARY"; then
    echo -e "${GREEN}Successfully signed osbx-standalone${NC}"
else
    echo -e "${RED}Error: Failed to sign binary${NC}"
    exit 1
fi

# Verify signature
echo -e "${GREEN}Verifying signature...${NC}"
codesign -v -v "$BINARY"

echo ""
echo -e "${GREEN}Done!${NC} You can now run:"
echo "  $BINARY --no-sandbox [paths...]"
echo ""
echo "Note: The binary now has the same entitlements as the target app."
echo "The kernel will apply sandbox rules based on these entitlements."
