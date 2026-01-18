# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-01-18

### Added
- **`oinstances` command**: Efficiently find class instances in memory
  - Scans heap memory for instances of specified class (including subclasses)
  - Adapts heap.py's efficient C code generation for maximum performance
  - Uses malloc zone introspection and binary search for speed
  - Optional scanning modes: `--stack`, `--segments`, `--vm-regions`
  - Limit control with `-M/--max-matches` flag
  - Works on both macOS and iOS

### Changed
- **Test Suite Optimization**: Dramatically improved test performance and maintainability
  - **test_ocls.py optimization**: 884 lines → 320 lines (64% reduction)
    - 75% fewer cache reloads via strategic warmup
    - Optimized test ordering for cache reuse
    - Added `OclsValidators` class with 11 specialized validators
  - **Cross-cutting improvements**: Added 7 universal validators to test_helpers.py
    - `method_resolved()` - Method resolution validation (saves ~200 lines across 8 files)
    - `contains_hex_address()` - Hex address validation (saves ~120 lines across 6 files)
    - `flag_accepted()` - Flag acceptance validation (saves ~72 lines across 4 files)
    - `private_class_optional()` - Private class handling (saves ~150 lines across 5 files)
    - `sorted_list_section()` - Sorted list validation (saves ~175 lines across 7 files)
    - `multiple_items_created()` - Multiple item validation (saves ~150 lines)
    - `count_in_range()` - Generic count extraction
  - **Estimated total impact**: ~800-900 lines reduction potential across all 10 test files
  - **Performance**: Estimated 70-80% faster when using shared session runner (planned)

## [1.3.2] - 2026-01-16

### Fixed
- `obrk` breakpoint failures on iOS system binaries with "error 9 sending breakpoint request"
  - Use raw IMP address from `class_getMethodImplementation()` directly
  - Use `HandleCommand("breakpoint set -a")` to match exact CLI behavior
  - Avoid going through `SBAddress` which can have section context issues

### Added
- `--verbose` / `-v` flag for `obrk` command for debugging breakpoint issues
  - Shows target/process state, frame info, parsed arguments
  - Shows raw IMP address vs SBAddress comparison
  - Shows module/section info and command execution details

## [1.3.1] - 2026-01-16

### Fixed
- `obrk` breakpoint failures on iOS system binaries with "error 9 sending breakpoint request"
  - Root cause: using `BreakpointCreateBySBAddress()` which includes section-relative context
  - Fix: use `BreakpointCreateByAddress()` with raw load address, matching `b <addr>` behavior

### Added
- Design documentation for iOS breakpoint error analysis (`docs/IOS_BREAKPOINT_ERRORS_DESIGN.md`)

## [1.3.0] - 2026-01-14

### Added
- Standalone sandbox scanner binary (`osbx`)
- Enhanced sandboxed app debugging support

## [1.2.3] - 2026-01-12

### Fixed
- Release workflow simplified to use build.sh dist
- Skip integration tests in CI when LLDB not available

## [1.2.2] - 2026-01-12

### Added
- LICENSE file (MIT)
- CI workflows for GitHub Actions
- EditorConfig for consistent code style
- Virtual environment support in build script

### Fixed
- CHANGELOG comparison URLs

## [1.2.1] - 2026-01-12

### Added
- Automatic string literal resolution from disassembly addresses
- Automatic selector resolution from disassembly addresses

## [1.2.0] - 2026-01-12

### Added
- `opool` command to find instances in autorelease pools
  - `--verbose` flag to show pool contents while searching
- `oinstance` command for detailed object inspection
  - Supports address, $variable, or expression syntax
- Pure Python core module (`objc_core.py`) for unit testable logic
- Unit test suite with pytest in `tests/unit/`
- Build script (`build.sh`) with standardized commands
- Git-based versioning (version derived from tags)

### Changed
- Separated LLDB-dependent code (`objc_utils.py`) from pure Python (`objc_core.py`)
- Replaced `package.py` with `build.sh package` command
- Added release workflow: `prepare-release` and `release X.Y.Z` commands

## [1.1.0] - 2025-12-31

### Added
- **ocall**: Call Objective-C methods directly from LLDB
  - Supports both class and instance methods
  - Handles method arguments properly
  - Returns formatted results
  - Expression evaluation support for complex arguments
- **owatch**: Auto-logging breakpoints for method observation
  - `--minimal` flag for compact timestamp-only output
  - `--stack` flag to include stack traces
  - Non-intrusive monitoring without stopping execution
- **ocls**: `--dylib` flag to filter classes by dynamic library
  - Batch size configuration (`--batch-size=N`)
  - Fast-path optimization for exact matches (<0.01s)
- **osel**: Category hinting on selector resolution
  - Shows category name when method comes from a category
  - Improved method resolution accuracy
- Automatic class hierarchy display in `ocls`
  - Single match: detailed hierarchy chain
  - 2-20 matches: compact per-class hierarchy
  - 21+ matches: simple class list
- Comprehensive test framework with pytest-style output
  - Consolidated validator utilities
  - Shared LLDB session for fast test execution
  - ~50% reduction in test boilerplate code

### Changed
- Renamed `ofind` command to `osel` for better naming consistency
- Renamed `oclasses` command to `ocls` for brevity
- Improved `ocls` with `--ivars` and `--properties` flags
- Enhanced UI conventions with consistent gray text for secondary info
- Optimized batch size to 35 for best performance
- Updated all documentation to reflect new command names
- Integrated category detection more cleanly in `osel`
- Code review and cleanup

### Performance
- **ocls**: Fast-path optimization for exact matches (<0.01s)
- Optimal batch size identified through testing: 35 items
- Shared test infrastructure reduces test time from ~120s to ~15-25s

## [1.0.0] - Initial Release

### Added
- **obrk**: Set breakpoints on Objective-C methods using familiar syntax (`-[Class selector:]`)
- **osel** (formerly ofind): Search for selectors in any Objective-C class
  - Wildcard pattern matching (`*` and `?`)
  - Case-insensitive substring matching
  - Lists both instance and class methods
- **ocls** (formerly oclasses): Find and list Objective-C classes
  - High-performance batched implementation
  - Per-process caching for instant subsequent queries
  - Wildcard and substring pattern matching
  - Configurable batch size for performance tuning
  - Verbose mode with detailed timing metrics
- Automatic installation script (`install.py`) for `.lldbinit` management
- Versioning system
- Comprehensive documentation

### Technical Details
- Runtime resolution using `NSClassFromString`, `NSSelectorFromString`, and `class_getMethodImplementation`
- Works with private classes and methods
- Supports both instance methods (`-`) and class methods (`+`)
- LLDB Python scripting API

[Unreleased]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.3...v1.3.0
[1.2.3]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/alan-phobos-org/lldb-objc/releases/tag/v1.0.0

