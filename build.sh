#!/bin/bash
set -euo pipefail

VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "dev")

# Python 3.11 path for integration tests (macOS)
PYTHON311="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"

case "${1:-help}" in
    version)
        echo "$VERSION"
        ;;
    test)
        echo "Running unit tests..."
        pytest tests/unit/ -v
        ;;
    test-int)
        echo "Running integration tests..."
        if [ -x "$PYTHON311" ]; then
            "$PYTHON311" ./tests/run_all_tests.py
        else
            echo "Python 3.11 not found at $PYTHON311"
            echo "Trying system python3..."
            python3 ./tests/run_all_tests.py
        fi
        ;;
    test-quick)
        echo "Running quick integration tests..."
        if [ -x "$PYTHON311" ]; then
            "$PYTHON311" ./tests/run_all_tests.py --quick
        else
            python3 ./tests/run_all_tests.py --quick
        fi
        ;;
    test-all)
        echo "Running all tests..."
        $0 test
        $0 test-int
        ;;
    lint)
        echo "Running linters..."
        # Check if ruff is available, otherwise use flake8
        if command -v ruff &> /dev/null; then
            ruff check scripts/ tests/ --fix
            ruff format scripts/ tests/
        elif command -v flake8 &> /dev/null; then
            flake8 scripts/ tests/ --max-line-length=120
        else
            echo "No linter found (install ruff or flake8)"
            exit 1
        fi
        ;;
    check)
        # Full pre-commit check
        $0 lint
        $0 test
        $0 test-quick
        ;;
    dist)
        # Run checks first
        $0 check

        echo "Creating release package..."

        # Create dist directory
        DIST_DIR="dist"
        rm -rf "$DIST_DIR"
        mkdir -p "$DIST_DIR/lldb-objc/scripts"

        # Copy files
        cp install.py "$DIST_DIR/lldb-objc/"
        cp README.md "$DIST_DIR/lldb-objc/" 2>/dev/null || true
        cp LICENSE "$DIST_DIR/lldb-objc/" 2>/dev/null || true
        cp CHANGELOG.md "$DIST_DIR/lldb-objc/" 2>/dev/null || true

        # Copy scripts
        cp scripts/__init__.py "$DIST_DIR/lldb-objc/scripts/"
        cp scripts/objc_*.py "$DIST_DIR/lldb-objc/scripts/"
        cp scripts/version.py "$DIST_DIR/lldb-objc/scripts/"

        # Write version file with git version
        cat > "$DIST_DIR/lldb-objc/scripts/version.py" << EOF
#!/usr/bin/env python3
"""Version information for LLDB Objective-C Tools."""

__version__ = "$VERSION"
__author__ = "Alan"
__description__ = "LLDB commands for Objective-C method introspection and debugging"
EOF

        # Create zip
        ZIP_NAME="lldb-objc-${VERSION}.zip"
        (cd "$DIST_DIR" && zip -r "../$ZIP_NAME" lldb-objc)

        echo ""
        echo "Created: $ZIP_NAME"
        ls -la "$ZIP_NAME"

        # Cleanup
        rm -rf "$DIST_DIR"
        ;;
    deploy-local)
        # Build dist and install locally
        $0 dist

        ZIP_NAME="lldb-objc-${VERSION}.zip"
        TEMP_DIR=$(mktemp -d)

        echo ""
        echo "Installing locally from $ZIP_NAME..."

        # Extract and install
        unzip -q "$ZIP_NAME" -d "$TEMP_DIR"
        (cd "$TEMP_DIR/lldb-objc" && python3 install.py)

        # Cleanup
        rm -rf "$TEMP_DIR"

        echo ""
        echo "✓ Installed lldb-objc $VERSION locally"
        ;;
    prepare-release)
        # Run all checks and tests required before release
        echo "=== Preparing release ==="
        echo ""

        # Step 1: Full integration tests
        echo "Step 1/3: Running full integration tests..."
        $0 test-int
        echo "✓ Integration tests passed"
        echo ""

        # Step 2: Create dist (runs check first, then packages)
        echo "Step 2/3: Creating dist package..."
        $0 dist
        echo "✓ Package created successfully"
        echo ""

        # Step 3: Show changes since last tag
        echo "Step 3/3: Changes since last release..."
        echo ""
        LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
        if [ -n "$LAST_TAG" ]; then
            echo "Last release: $LAST_TAG"
            echo ""
            echo "Commits since $LAST_TAG:"
            git log --oneline "$LAST_TAG"..HEAD
            echo ""
            echo "Files changed:"
            git diff --stat "$LAST_TAG"..HEAD | tail -1
        else
            echo "No previous release tag found"
            echo ""
            echo "All commits:"
            git log --oneline
        fi

        echo ""
        echo "=== Release preparation complete ==="
        echo ""
        echo "Next steps:"
        echo "  1. Review the changes above"
        echo "  2. Update CHANGELOG.md with release notes"
        echo "  3. Run: ./build.sh release <version>"
        echo ""
        echo "Example: ./build.sh release 1.1.0"
        ;;
    release)
        # Create a release commit and tag
        RELEASE_VERSION="${2:-}"

        if [ -z "$RELEASE_VERSION" ]; then
            echo "Usage: $0 release <version>"
            echo "Example: $0 release 1.1.0"
            exit 1
        fi

        # Validate version format (semver)
        if ! echo "$RELEASE_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
            echo "ERROR: Invalid version format. Use semantic versioning (e.g., 1.2.3)"
            exit 1
        fi

        TAG="v$RELEASE_VERSION"

        # Check if tag already exists
        if git rev-parse "$TAG" >/dev/null 2>&1; then
            echo "ERROR: Tag $TAG already exists"
            exit 1
        fi

        # Check for uncommitted changes (excluding CHANGELOG.md which we expect to be modified)
        if ! git diff --quiet HEAD -- . ':!CHANGELOG.md'; then
            echo "ERROR: Uncommitted changes exist (other than CHANGELOG.md)"
            echo "Please commit or stash changes before releasing"
            git status --short
            exit 1
        fi

        # Check that CHANGELOG.md has an entry for this version
        if ! grep -q "## \[$RELEASE_VERSION\]" CHANGELOG.md; then
            echo "ERROR: CHANGELOG.md does not contain entry for version $RELEASE_VERSION"
            echo "Please add a '## [$RELEASE_VERSION]' section to CHANGELOG.md"
            exit 1
        fi

        # Check if CHANGELOG.md is modified (it should be, with the new version)
        if git diff --quiet HEAD -- CHANGELOG.md; then
            echo "WARNING: CHANGELOG.md has no uncommitted changes"
            echo "Did you forget to update the changelog?"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi

        echo "Creating release $TAG..."

        # Stage and commit CHANGELOG.md if modified
        if ! git diff --quiet HEAD -- CHANGELOG.md; then
            git add CHANGELOG.md
        fi

        # Create release commit (if there are staged changes)
        if ! git diff --cached --quiet; then
            git commit -m "Release $TAG"
            echo "✓ Created release commit"
        else
            echo "No changes to commit"
        fi

        # Create annotated tag
        git tag -a "$TAG" -m "Release $TAG"
        echo "✓ Created tag $TAG"

        # Create release dist
        $0 dist
        echo "✓ Created release dist"

        echo ""
        echo "=== Release $TAG created ==="
        echo ""
        echo "Next steps:"
        echo "  1. Review: git log -1 && git show $TAG"
        echo "  2. Push:   git push origin main $TAG"
        ;;
    clean)
        rm -rf dist/ lldb-objc-*.zip .pytest_cache/ __pycache__/
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        find . -type f -name "*.pyc" -delete 2>/dev/null || true
        ;;
    *)
        echo "LLDB Objective-C Tools - Build Script"
        echo ""
        echo "Usage: $0 {command}"
        echo ""
        echo "Commands:"
        echo "  version          Show current version (from git)"
        echo "  test             Run unit tests (pytest)"
        echo "  test-int         Run integration tests (full suite)"
        echo "  test-quick       Run quick integration tests"
        echo "  test-all         Run unit + integration tests"
        echo "  lint             Run linters (ruff or flake8)"
        echo "  check            Full pre-commit check (lint + test + test-quick)"
        echo "  dist             Create release zip package"
        echo "  deploy-local     Build dist and install locally"
        echo "  prepare-release  Run all release checks and show changes"
        echo "  release X.Y.Z    Create release commit and tag"
        echo "  clean            Remove build artifacts"
        ;;
esac
