# Project Roadmap

## Vision

A comprehensive set of LLDB commands for Objective-C runtime introspection, making it easy to debug and explore any Objective-C code including private frameworks.

## Current Stage: v1.3 (Stable)

9 commands covering core debugging use cases: `obrk`, `osel`, `ocls`, `ocall`, `owatch`, `opool`, `oinstance`, `oinstances`, `osbx`.

Standalone sandbox scanner binary available at `tools/osbx-standalone/`.

The `oinstances` command efficiently scans memory for class instances using heap.py's optimized techniques.

## TODO

### v1.5 

* Make HelloWorld binaries more representative to test opool and oinstances a bit better
* Build test-smoke set up for testing against iPhone
* Re-optimise ocls - lots of experiments needed and probably 2/3 strategies to try on real-world examples (need test iPhone)