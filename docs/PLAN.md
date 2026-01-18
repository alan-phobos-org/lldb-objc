# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.3 (Stable)

9 commands covering core debugging use cases: `obrk`, `osel`, `ocls`, `ocall`, `owatch`, `opool`, `oinstance`, `oinstances`, `osbx`.

Standalone sandbox scanner binary available at `tools/osbx-standalone/`.

The `oinstances` command efficiently scans memory for class instances using heap.py's optimized techniques.

## TODO

### v1.6

Bugs:

* owatch shouldn't need - on selectors
* owatch `NameError: name 'extra_args' is not defined`

Feat:

* `omemlayout` needs pimping - ralph loop
* Re-optimise ocls - lots of experiments needed and probably 2/3 strategies to try on real-world examples (need test iPhone)
* ocls --selectors to list all and where from
