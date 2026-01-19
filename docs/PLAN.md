# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.5 (Stable)

13 commands covering core debugging use cases: `obrk`, `osel`, `ocls`, `ocall`, `owatch`, `opool`, `oinstance`, `oinstances`, `osbx`, `odump`, `oentitlements`, `okeychain`, `omemlayout`.

Standalone sandbox scanner binary available at `tools/osbx-standalone/`.

The `oinstances` command efficiently scans memory for class instances using heap.py's optimized techniques.

The `omemlayout` command displays process memory layout including stacks, heap regions, and shared memory.

The `okeychain` command provides keychain introspection with automatic process-specific keychain detection.

## TODO

### v1.6

Bugs:

* owatch shouldn't need - on selectors
* owatch `NameError: name 'extra_args' is not defined`
* okeychain: iOS fails with 'use of undeclared identifier SecKeychainOpen' - SecKeychainOpen is macOS-only, iOS has no keychain files
* okeychain: iOS fails with 'SecItemCopyMatching has unknown return type' - needs explicit cast or import
* opool: `ReadCStringFromMemory` returns NULL without error on iOS when _objc_autoreleasePoolPrint() returns invalid data
* oentitlements: XML parsing fails with "not well-formed invalid token" - entitlements data may have trailing null bytes or garbage

Feat:

* `omemlayout` needs pimping - ralph loop
* Re-optimise ocls - lots of experiments needed and probably 2/3 strategies to try on real-world examples (need test iPhone)
* ocls --selectors to list all and where from
