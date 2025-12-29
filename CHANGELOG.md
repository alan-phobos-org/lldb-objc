# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **ocall**: Call Objective-C methods directly from LLDB
  - Supports both class and instance methods
  - Handles method arguments properly
  - Returns formatted results
- **owatch**: Auto-logging breakpoints for method observation
  - `--minimal` flag for compact timestamp-only output
  - `--stack` flag to include stack traces
  - Non-intrusive monitoring without stopping execution
- **oprotos**: Protocol conformance search
  - Find classes conforming to specific protocols
  - `--list` flag to enumerate available protocols
  - Wildcard pattern matching for protocol names
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

[Unreleased]: https://github.com/yourusername/lldb-objc/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/lldb-objc/releases/tag/v1.0.0
