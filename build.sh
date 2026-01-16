#!/bin/bash
set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VERSION=$(git -C "$ROOT_DIR" describe --tags --always --dirty 2>/dev/null || echo "dev")
DIST_DIR="$ROOT_DIR/dist"
PACKAGE_DIR="lldb-objc-${VERSION}"
ZIP_NAME="lldb-objc-${VERSION}.zip"
VENV_DIR="$ROOT_DIR/.venv"

# =============================================================================
# Helper Functions
# =============================================================================

die() {
    echo "ERROR: $1" >&2
    exit 1
}

# Ensure venv exists and has dependencies installed
ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating venv at $VENV_DIR..."
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip -q
        "$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements-dev.txt" -q
        echo "✓ Venv created and dependencies installed"
    fi
}

# Run Python using the venv
run_python() {
    ensure_venv
    "$VENV_DIR/bin/python" "$@"
}

run_pytest() {
    run_python -m pytest "$@"
}

run_ruff() {
    ensure_venv
    "$VENV_DIR/bin/ruff" "$@"
}

show_help() {
    cat << 'EOF'
LLDB Objective-C Tools - Build Script

Usage: ./build.sh {command}

Commands:
  version          Show current version (from git)
  test             Run unit tests (pytest)
  test-int         Run integration tests (full suite)
  test-quick       Run quick integration tests
  test-all         Run unit + integration tests
  lint             Run linters (ruff or flake8)
  check            Full pre-commit check (lint + test + test-quick)
  dist             Create release zip package
  deploy-local     Build dist and install locally
  prepare-release  Run all release checks and show changes
  release X.Y.Z    Create release commit and tag
  clean            Remove build artifacts
  status           Show project status (working copy, remote, CI, releases)
EOF
}

cmd_version() {
    echo "$VERSION"
}

cmd_test() {
    echo "Running unit tests..."
    run_pytest "$ROOT_DIR/tests/unit/" -v
}

cmd_test_int() {
    echo "Running integration tests..."
    run_python "$ROOT_DIR/tests/run_all_tests.py"
}

cmd_test_quick() {
    echo "Running quick integration tests..."
    run_python "$ROOT_DIR/tests/run_all_tests.py" --quick
}

cmd_test_all() {
    echo "Running all tests..."
    cmd_test
    cmd_test_int
}

cmd_lint() {
    echo "Running linters..."
    run_ruff check "$ROOT_DIR/scripts/" "$ROOT_DIR/tests/" --fix
    run_ruff format "$ROOT_DIR/scripts/" "$ROOT_DIR/tests/"
}

cmd_check() {
    cmd_lint
    cmd_test
    # Only run integration tests if LLDB is available (skip in CI)
    if command -v lldb >/dev/null 2>&1; then
        cmd_test_quick
    else
        echo "Skipping integration tests (LLDB not available)"
    fi
}

cmd_dist() {
    cmd_check

    echo "Creating release package..."
    rm -rf "$DIST_DIR"
    mkdir -p "$DIST_DIR/$PACKAGE_DIR/scripts"

    # Copy root files
    cp "$ROOT_DIR/install.py" "$DIST_DIR/$PACKAGE_DIR/"
    cp "$ROOT_DIR/README.md" "$DIST_DIR/$PACKAGE_DIR/" 2>/dev/null || true
    cp "$ROOT_DIR/LICENSE" "$DIST_DIR/$PACKAGE_DIR/" 2>/dev/null || true
    cp "$ROOT_DIR/CHANGELOG.md" "$DIST_DIR/$PACKAGE_DIR/" 2>/dev/null || true

    # Copy scripts
    cp "$ROOT_DIR/scripts/__init__.py" "$DIST_DIR/$PACKAGE_DIR/scripts/"
    cp "$ROOT_DIR"/scripts/objc_*.py "$DIST_DIR/$PACKAGE_DIR/scripts/"

    # Generate version.py with embedded version (strip leading 'v' if present)
    EMBED_VERSION="${VERSION#v}"
    cat > "$DIST_DIR/$PACKAGE_DIR/scripts/version.py" << EOF
#!/usr/bin/env python3
"""Version information for LLDB Objective-C Tools."""

__version__ = "$EMBED_VERSION"
__author__ = "Alan"
__description__ = "LLDB commands for Objective-C method introspection and debugging"
EOF

    # Copy osbx-standalone tools
    mkdir -p "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/sandbox_profiles"
    cp "$ROOT_DIR/tools/osbx-standalone/main.c" "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/"
    cp "$ROOT_DIR/tools/osbx-standalone/Makefile" "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/"
    cp "$ROOT_DIR/tools/osbx-standalone/osbx_spawn.py" "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/"
    cp "$ROOT_DIR/tools/osbx-standalone/sign-with-entitlements.sh" "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/"
    cp "$ROOT_DIR/tools/osbx-standalone/README.md" "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/"
    cp "$ROOT_DIR"/tools/osbx-standalone/sandbox_profiles/*.sb "$DIST_DIR/$PACKAGE_DIR/tools/osbx-standalone/sandbox_profiles/"

    # Create zip
    (cd "$DIST_DIR" && zip -r "$ZIP_NAME" "$PACKAGE_DIR" && rm -rf "$PACKAGE_DIR")

    echo ""
    echo "Created: $DIST_DIR/$ZIP_NAME"
    ls -la "$DIST_DIR/$ZIP_NAME"
}

cmd_deploy_local() {
    cmd_dist

    TEMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TEMP_DIR"' EXIT

    echo ""
    echo "Installing locally from $DIST_DIR/$ZIP_NAME..."
    unzip -q "$DIST_DIR/$ZIP_NAME" -d "$TEMP_DIR"
    (cd "$TEMP_DIR/$PACKAGE_DIR" && python3 install.py)

    echo ""
    echo "✓ Installed lldb-objc $VERSION locally"
}

cmd_prepare_release() {
    echo "=== Preparing release ==="
    echo ""

    echo "Step 1/3: Running full integration tests..."
    cmd_test_int
    echo "✓ Integration tests passed"
    echo ""

    echo "Step 2/3: Creating dist package..."
    cmd_dist
    echo "✓ Package created successfully"
    echo ""

    echo "Step 3/3: Changes since last release..."
    echo ""
    LAST_TAG=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null || echo "")
    if [ -n "$LAST_TAG" ]; then
        echo "Last release: $LAST_TAG"
        echo ""
        echo "Commits since $LAST_TAG:"
        git -C "$ROOT_DIR" log --oneline "$LAST_TAG"..HEAD
        echo ""
        echo "Files changed:"
        git -C "$ROOT_DIR" diff --stat "$LAST_TAG"..HEAD | tail -1
    else
        echo "No previous release tag found"
        echo ""
        echo "All commits:"
        git -C "$ROOT_DIR" log --oneline
    fi

    echo ""
    echo "=== Release preparation complete ==="
    echo ""
    echo "Next steps:"
    echo "  1. Review the changes above"
    echo "  2. Update CHANGELOG.md with release notes"
    echo "  3. Run: ./build.sh release <version>"
    echo ""
    echo "Example: ./build.sh release 1.2.2"
}

cmd_release() {
    RELEASE_VERSION="${1:-}"
    [ -z "$RELEASE_VERSION" ] && die "Usage: $0 release <version>\nExample: $0 release 1.2.2"

    # Validate semver format
    echo "$RELEASE_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' \
        || die "Invalid version format. Use semantic versioning (e.g., 1.2.3)"

    TAG="v$RELEASE_VERSION"

    # Validation checks
    git -C "$ROOT_DIR" rev-parse "$TAG" >/dev/null 2>&1 && die "Tag $TAG already exists"

    if ! git -C "$ROOT_DIR" diff --quiet HEAD -- . ':!CHANGELOG.md'; then
        echo "Uncommitted changes exist (other than CHANGELOG.md):"
        git -C "$ROOT_DIR" status --short
        die "Please commit or stash changes before releasing"
    fi

    grep -q "## \[$RELEASE_VERSION\]" "$ROOT_DIR/CHANGELOG.md" \
        || die "CHANGELOG.md does not contain entry for version $RELEASE_VERSION\nPlease add a '## [$RELEASE_VERSION]' section"

    # Warn if changelog not modified
    if git -C "$ROOT_DIR" diff --quiet HEAD -- CHANGELOG.md; then
        echo "WARNING: CHANGELOG.md has no uncommitted changes"
        echo "Did you forget to update the changelog?"
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        [[ $REPLY =~ ^[Yy]$ ]] || exit 1
    fi

    echo "Creating release $TAG..."

    # Stage and commit CHANGELOG.md if modified
    if ! git -C "$ROOT_DIR" diff --quiet HEAD -- CHANGELOG.md; then
        git -C "$ROOT_DIR" add CHANGELOG.md
    fi

    if ! git -C "$ROOT_DIR" diff --cached --quiet; then
        git -C "$ROOT_DIR" commit -m "Release $TAG"
        echo "✓ Created release commit"
    else
        echo "No changes to commit"
    fi

    git -C "$ROOT_DIR" tag -a "$TAG" -m "Release $TAG"
    echo "✓ Created tag $TAG"

    cmd_dist
    echo "✓ Created release dist"

    echo ""
    echo "=== Release $TAG created ==="
    echo ""
    echo "Next steps:"
    echo "  1. Review: git log -1 && git show $TAG"
    echo "  2. Push:   git push origin main $TAG"
}

cmd_clean() {
    rm -rf "$DIST_DIR" "$ROOT_DIR"/lldb-objc-*.zip "$ROOT_DIR/.pytest_cache" "$ROOT_DIR/__pycache__"
    find "$ROOT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find "$ROOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    echo "✓ Cleaned build artifacts"
}

cmd_status() {
    echo "=== Project Status ==="
    echo ""

    # Version
    echo "Version: $VERSION"
    LAST_TAG=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null || echo "none")
    echo "Latest release: $LAST_TAG"
    echo ""

    # Working copy
    echo "--- Working Copy ---"
    if git -C "$ROOT_DIR" diff --quiet && git -C "$ROOT_DIR" diff --cached --quiet; then
        UNTRACKED=$(git -C "$ROOT_DIR" ls-files --others --exclude-standard | wc -l | tr -d ' ')
        if [ "$UNTRACKED" -eq 0 ]; then
            echo "Clean"
        else
            echo "Clean (${UNTRACKED} untracked files)"
        fi
    else
        echo "Dirty"
        git -C "$ROOT_DIR" status --short | head -10
        TOTAL=$(git -C "$ROOT_DIR" status --short | wc -l | tr -d ' ')
        [ "$TOTAL" -gt 10 ] && echo "... and $((TOTAL - 10)) more"
    fi
    echo ""

    # Remote sync
    echo "--- Remote Status ---"
    git -C "$ROOT_DIR" fetch origin --quiet 2>/dev/null || echo "Warning: could not fetch origin"
    LOCAL=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null)
    REMOTE=$(git -C "$ROOT_DIR" rev-parse origin/main 2>/dev/null || echo "unknown")
    if [ "$LOCAL" = "$REMOTE" ]; then
        echo "In sync with origin/main"
    else
        AHEAD=$(git -C "$ROOT_DIR" rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
        BEHIND=$(git -C "$ROOT_DIR" rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
        [ "$AHEAD" != "0" ] && echo "Ahead of origin/main by $AHEAD commits"
        [ "$BEHIND" != "0" ] && echo "Behind origin/main by $BEHIND commits"
    fi
    echo ""

    # CI status (requires gh CLI)
    echo "--- CI Status ---"
    if command -v gh &>/dev/null; then
        (cd "$ROOT_DIR" && gh run list --limit 3 2>/dev/null) || echo "Could not fetch CI status"
    else
        echo "gh CLI not installed - skipping CI status"
    fi
    echo ""

    # Recent releases
    echo "--- Recent Releases ---"
    if command -v gh &>/dev/null; then
        (cd "$ROOT_DIR" && gh release list --limit 3 2>/dev/null) || echo "No releases found"
    else
        git -C "$ROOT_DIR" tag --sort=-creatordate | head -3 || echo "No tags found"
    fi
    echo ""

    # Changes since last release
    if [ "$LAST_TAG" != "none" ]; then
        echo "--- Changes Since $LAST_TAG ---"
        COMMIT_COUNT=$(git -C "$ROOT_DIR" rev-list --count "$LAST_TAG"..HEAD 2>/dev/null || echo "0")
        echo "$COMMIT_COUNT commits"
        if [ "$COMMIT_COUNT" != "0" ] && [ "$COMMIT_COUNT" -lt 20 ]; then
            git -C "$ROOT_DIR" log --oneline "$LAST_TAG"..HEAD
        elif [ "$COMMIT_COUNT" -ge 20 ]; then
            git -C "$ROOT_DIR" log --oneline "$LAST_TAG"..HEAD | head -10
            echo "... and $((COMMIT_COUNT - 10)) more commits"
        fi
    fi
}

# =============================================================================
# Commands
# =============================================================================

case "${1:-help}" in
    version)
        cmd_version
        ;;

    test)
        cmd_test
        ;;

    test-int)
        cmd_test_int
        ;;

    test-quick)
        cmd_test_quick
        ;;

    test-all)
        cmd_test_all
        ;;

    lint)
        cmd_lint
        ;;

    check)
        cmd_check
        ;;

    dist)
        cmd_dist
        ;;

    deploy-local)
        cmd_deploy_local
        ;;

    prepare-release)
        cmd_prepare_release
        ;;

    release)
        cmd_release "${2:-}"
        ;;

    clean)
        cmd_clean
        ;;

    status)
        cmd_status
        ;;

    help|*)
        show_help
        ;;
esac
