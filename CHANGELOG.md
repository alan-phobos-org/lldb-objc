# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- `--claude-haiku` flag for `oexplain` and `odecompile` commands
- Automatic string literal resolution from disassembly addresses
- Automatic selector resolution from disassembly addresses
- Platform/architecture info included in LLM context

### Changed
- Improved LLM prompts with ARM64 calling convention notes

## [1.2.0] - 2026-01-12

### Added
- `oexplain` command for LLM-based disassembly explanation
  - `--annotate` flag for line-by-line annotation
  - `--claude` flag to use Claude CLI instead of llm
- `odecompile` command for LLM-based decompilation
  - Generates readable pseudo-code from disassembly
  - `--claude` flag to use Claude CLI instead of llm
- `opool` command to find instances in autorelease pools
  - `--verbose` flag to show pool contents while searching
- `oinstance` command for detailed object inspection
  - Supports address, $variable, or expression syntax
- Shared LLM utilities (`objc_llm.py`) for symbol lookup and CLI wrappers
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
- **oprotos**: Protocol conformance search
  - Find classes conforming to specific protocols
  - `--list` flag to enumerate available protocols
  - Wildcard pattern matching for protocol names
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

[Unreleased]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.2...HEAD
[1.2.2]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/alan-phobos-org/lldb-objc/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/alan-phobos-org/lldb-objc/releases/tag/v1.0.0

