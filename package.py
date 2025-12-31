#!/usr/bin/env python3
"""
Packaging script for LLDB Objective-C Tools.

Creates a release zip file containing all necessary scripts for distribution.

Usage:
    ./package.py              # Create release zip in current directory
    ./package.py --output DIR # Create release zip in specified directory
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path

# Import version
try:
    from version import __version__
except ImportError:
    __version__ = "unknown"

# Configuration
SCRIPT_DIR = Path(__file__).parent.absolute()

# Files to include in the release
RELEASE_FILES = [
    "objc_breakpoint.py",
    "objc_sel.py",
    "objc_cls.py",
    "objc_call.py",
    "objc_watch.py",
    "objc_protos.py",
    "objc_utils.py",
    "install.py",
    "version.py",
    "README.md",
    "LICENSE",
]


def create_release(output_dir: Path) -> Path:
    """Create a release zip file.

    Args:
        output_dir: Directory to create the zip file in

    Returns:
        Path to the created zip file
    """
    zip_name = f"lldb-objc-{__version__}.zip"
    zip_path = output_dir / zip_name

    print(f"Creating release package: {zip_path}")
    print(f"Version: {__version__}")
    print()

    # Collect files
    files_to_package = []
    missing_required = []

    for filename in RELEASE_FILES:
        file_path = SCRIPT_DIR / filename
        if file_path.exists():
            files_to_package.append((filename, file_path))
        elif filename in ("README.md", "LICENSE"):
            # Optional files
            print(f"  Skipping (not found): {filename}")
        else:
            missing_required.append(filename)

    # Check for missing required files
    if missing_required:
        print("Error: Missing required files:", file=sys.stderr)
        for f in missing_required:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    # Create zip file
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, file_path in files_to_package:
            # Store files in a subdirectory named lldb-objc
            arcname = f"lldb-objc/{filename}"
            zf.write(file_path, arcname)
            print(f"  Added: {filename}")

    print()
    print(f"Release package created: {zip_path}")
    print(f"Size: {zip_path.stat().st_size:,} bytes")

    # Show contents
    print()
    print("Contents:")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            print(f"  {info.filename} ({info.file_size:,} bytes)")

    return zip_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=f"Package LLDB Objective-C Tools v{__version__} for release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./package.py                    Create release zip in current directory
  ./package.py --output ~/releases  Create release zip in specified directory
        """
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path.cwd(),
        help="Output directory for the release zip (default: current directory)"
    )

    args = parser.parse_args()

    # Validate output directory
    if not args.output.exists():
        print(f"Creating output directory: {args.output}")
        args.output.mkdir(parents=True)
    elif not args.output.is_dir():
        print(f"Error: Output path is not a directory: {args.output}", file=sys.stderr)
        sys.exit(1)

    try:
        zip_path = create_release(args.output)
        print()
        print("To install from this release:")
        print(f"  1. Unzip: unzip {zip_path.name}")
        print("  2. Run: cd lldb-objc && ./install.py")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
