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
    echo "Usage: $0 /path/to/Target [signing-identity]"
    echo ""
    echo "Sign osbx-standalone with the same entitlements as the target app or binary."
    echo ""
    echo "Arguments:"
    echo "  /path/to/Target       Path to app bundle (.app) or standalone binary"
    echo "  signing-identity      Optional: Code signing identity (default: ad-hoc)"
    echo ""
    echo "Examples:"
    echo "  $0 /Applications/Safari.app"
    echo "  $0 /System/Library/PrivateFrameworks/ApplePushService.framework/apsd"
    echo "  $0 /usr/libexec/rapportd"
    echo "  $0 /Applications/MyApp.app \"Developer ID Application: My Name\""
    exit 1
}

# Check arguments
if [ $# -lt 1 ]; then
    usage
fi

TARGET="$1"
SIGNING_IDENTITY="${2:--}" # Default to ad-hoc signing

# Validate target exists
if [ ! -e "$TARGET" ]; then
    echo -e "${RED}Error: Target not found: $TARGET${NC}"
    exit 1
fi

# Determine if target is an app bundle or standalone binary
if [ -d "$TARGET" ] && [ -d "$TARGET/Contents/MacOS" ]; then
    # macOS app bundle
    APP_NAME=$(basename "$TARGET" .app)
    TARGET_BINARY="$TARGET/Contents/MacOS/$APP_NAME"

    # Try to find the actual binary from Info.plist
    if [ -f "$TARGET/Contents/Info.plist" ]; then
        PLIST_EXEC=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$TARGET/Contents/Info.plist" 2>/dev/null || true)
        if [ -n "$PLIST_EXEC" ]; then
            TARGET_BINARY="$TARGET/Contents/MacOS/$PLIST_EXEC"
        fi
    fi

    if [ ! -f "$TARGET_BINARY" ]; then
        echo -e "${RED}Error: Could not find executable in app bundle${NC}"
        echo "Expected: $TARGET_BINARY"
        exit 1
    fi
elif [ -f "$TARGET" ]; then
    # Standalone binary (daemon, system binary, framework executable, etc.)
    TARGET_BINARY="$TARGET"

    # Verify it's actually an executable (Mach-O binary)
    if ! file "$TARGET_BINARY" | grep -q "Mach-O"; then
        echo -e "${RED}Error: Target is not a Mach-O executable: $TARGET${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: Target is neither an app bundle nor a binary: $TARGET${NC}"
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

# Extract entitlements (use :- to get raw XML plist format, not human-readable)
if ! codesign -d --entitlements :- "$TARGET_BINARY" > "$ENTITLEMENTS_FILE" 2>/dev/null; then
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

# Check for restricted private entitlements (only work with Apple-signed binaries)
FILTERED_ENTITLEMENTS_FILE=$(mktemp /tmp/filtered_entitlements.XXXXXX.plist)
trap "rm -f $ENTITLEMENTS_FILE $FILTERED_ENTITLEMENTS_FILE" EXIT

HAS_PRIVATE_ENTITLEMENTS=0
if grep -q "com.apple.private\." "$ENTITLEMENTS_FILE"; then
    HAS_PRIVATE_ENTITLEMENTS=1
    echo -e "${YELLOW}Warning: Target has restricted com.apple.private.* entitlements${NC}"
    echo "These only work with Apple-signed binaries - filtering them out..."
    echo ""

    # Use plutil to convert to XML, filter with Python, convert back
    # This is more robust than sed for plist manipulation
    python3 - "$ENTITLEMENTS_FILE" "$FILTERED_ENTITLEMENTS_FILE" << 'PYEOF'
import plistlib
import sys

with open(sys.argv[1], 'rb') as f:
    try:
        ents = plistlib.load(f)
    except:
        # Empty or invalid plist
        ents = {}

# Filter to keep only entitlements that work with ad-hoc signing
# Note: com.apple.security.app-sandbox requires system container setup
# and doesn't work properly with ad-hoc signed binaries
ALLOWED_ENTITLEMENTS = [
    'com.apple.security.application-groups',
    'com.apple.security.files.',              # File access entitlements (prefix)
    'com.apple.security.network.',            # Network entitlements (prefix)
    'com.apple.security.temporary-exception.',  # Temporary exceptions (prefix)
]

# Explicitly excluded (require Apple signing or system support)
EXCLUDED_ENTITLEMENTS = [
    'com.apple.security.app-sandbox',  # Requires container setup by system
]

filtered = {}
removed = []
for key, value in ents.items():
    if key in EXCLUDED_ENTITLEMENTS:
        removed.append(key + " (requires system container)")
        continue
    is_allowed = any(
        key == e or (e.endswith('.') and key.startswith(e))
        for e in ALLOWED_ENTITLEMENTS
    )
    if is_allowed:
        filtered[key] = value
    else:
        removed.append(key)

if removed:
    print(f"Filtered out {len(removed)} restricted entitlements:")
    for r in removed[:10]:
        print(f"  - {r}")
    if len(removed) > 10:
        print(f"  ... and {len(removed) - 10} more")
    print()

with open(sys.argv[2], 'wb') as f:
    plistlib.dump(filtered, f)
PYEOF

    # Use filtered file
    mv "$FILTERED_ENTITLEMENTS_FILE" "$ENTITLEMENTS_FILE"
fi

# Show extracted entitlements
echo -e "${GREEN}Entitlements to apply:${NC}"
plutil -p "$ENTITLEMENTS_FILE" 2>/dev/null | head -30 || cat "$ENTITLEMENTS_FILE" | head -30
echo ""

# Check for sandbox entitlement in the original (not filtered) entitlements
if codesign -d --entitlements :- "$TARGET_BINARY" 2>/dev/null | grep -q "com.apple.security.app-sandbox"; then
    HAS_APP_SANDBOX=1
else
    HAS_APP_SANDBOX=0
fi

if [ "$HAS_APP_SANDBOX" -eq 1 ]; then
    echo -e "${YELLOW}Note: Target uses App Sandbox (com.apple.security.app-sandbox)${NC}"
    echo "This entitlement requires system container setup and doesn't work with ad-hoc signing."
    echo "The scanner will run WITHOUT sandbox restrictions."
    echo ""
    echo "To test sandbox behavior, use the --profile approach instead:"
    echo "  ./osbx-standalone --profile <sandbox_profile.sb> [paths...]"
elif [ "$HAS_PRIVATE_ENTITLEMENTS" -eq 1 ]; then
    echo -e "${YELLOW}Note: System daemons often use launchd sandbox profiles${NC}"
    echo "Consider using: ./osbx-standalone --profile /System/Library/Sandbox/Profiles/<daemon>.sb"
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
