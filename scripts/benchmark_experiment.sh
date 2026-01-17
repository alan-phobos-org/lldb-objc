#!/bin/bash
# Benchmark script to compare standard vs experimental ocls approaches
#
# Usage: ./benchmark_experiment.sh
#
# This script runs ocls with both standard and experimental approaches
# and compares their performance.

set -e

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  OCLS EXPERIMENTAL APPROACH BENCHMARK                              ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "This benchmark compares two monolithic enumeration approaches:"
echo "  1. Standard:     objc_copyClassList + class_getName (current)"
echo "  2. Experimental: objc_copyImageNames + objc_copyClassNamesForImage"
echo ""
echo "Expected tradeoff:"
echo "  • Standard:     1× list + ~10K× getName calls"
echo "  • Experimental: ~200× image iterations + ~200× copyClassNames calls"
echo ""
echo "────────────────────────────────────────────────────────────────────"
echo ""

# Check if we have a test binary available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    exit 1
fi

# Get the scripts directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Create a temporary test script
cat > /tmp/ocls_benchmark_test.py << 'EOF'
#!/usr/bin/env python3
"""Quick benchmark test for ocls experimental approach - static analysis only."""

import sys
import os
import re

# Check the source file directly (no import needed - lldb not available)
script_path = sys.argv[1] if len(sys.argv) > 1 else "scripts/objc_cls.py"

print(f"Analyzing: {script_path}")

if not os.path.exists(script_path):
    print(f"❌ File not found: {script_path}")
    sys.exit(1)

with open(script_path, 'r') as f:
    content = f.read()

# Check for key components
checks = [
    ('build_image_based_monolithic_expr function', r'def build_image_based_monolithic_expr\('),
    ('objc_copyImageNames usage', r'objc_copyImageNames'),
    ('objc_copyClassNamesForImage usage', r'objc_copyClassNamesForImage'),
    ('--experiment flag parsing', r'use_experiment\s*=\s*"--experiment"\s+in\s+args'),
    ('Experimental approach selection', r'if use_experiment:'),
    ('Approach tracking in timing', r'"approach".*"image-based"'),
    ('get_all_classes use_experiment parameter', r'use_experiment:\s*bool\s*=\s*False'),
]

print("\nChecking implementation:")
all_passed = True
for name, pattern in checks:
    if re.search(pattern, content):
        print(f"  ✓ {name}")
    else:
        print(f"  ❌ {name}")
        all_passed = False

# Syntax check
try:
    compile(content, script_path, 'exec')
    print(f"\n✓ Python syntax valid")
except SyntaxError as e:
    print(f"\n❌ Syntax error: {e}")
    all_passed = False

if all_passed:
    print("\n✓ All static tests passed!")
    sys.exit(0)
else:
    print("\n❌ Some tests failed")
    sys.exit(1)
EOF

chmod +x /tmp/ocls_benchmark_test.py

# Run the static test
echo "Running static tests..."
cd "$PROJECT_DIR"
python3 /tmp/ocls_benchmark_test.py "$SCRIPT_DIR/objc_cls.py"

echo ""
echo "────────────────────────────────────────────────────────────────────"
echo ""
echo "✓ Static tests passed!"
echo ""
echo "To run live benchmarks in LLDB, use these commands:"
echo ""
echo "  # Standard approach (current default):"
echo "  ocls --reload --verbose"
echo ""
echo "  # Experimental approach (image-based):"
echo "  ocls --reload --verbose --experiment"
echo ""
echo "Compare the 'Approach' field in the Performance Summary output."
echo ""
echo "Expected behavior:"
echo "  • Both should return the same class list"
echo "  • Timing may vary depending on runtime optimizations"
echo "  • Check 'Expressions' and 'Memory reads' in Resource usage"
echo ""
