#!/usr/bin/env python3
"""
Test script for ofind command.
Run this in LLDB to test the ofind functionality iteratively.
"""

# Test cases for IDSService
test_cases = [
    ("ofind IDSService", "List all selectors in IDSService"),
    ("ofind IDSService serviceIdentifier", "Find 'serviceIdentifier' selector"),
    ("ofind IDSService _internal", "Find '_internal' selector"),
    ("ofind IDSService service", "Find all selectors containing 'service'"),
    ("ofind IDSService *ternal", "Find selectors ending with 'ternal' (wildcard)"),
    ("ofind IDSService _init*", "Find selectors starting with '_init' (wildcard)"),
    ("ofind IDSService *service*", "Find selectors containing 'service' (wildcard)"),
]

print("=" * 60)
print("OFIND TEST SUITE")
print("=" * 60)
print("\nTest cases to run:")
for i, (cmd, desc) in enumerate(test_cases, 1):
    print(f"{i}. {cmd}")
    print(f"   → {desc}")

print("\n" + "=" * 60)
print("Run these commands in LLDB to test:")
print("=" * 60)
for cmd, _ in test_cases:
    print(f"  {cmd}")

print("\n" + "=" * 60)
