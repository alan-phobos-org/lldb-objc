# Makefile for osbx-standalone
#
# Build the standalone sandbox scanner binary.

CC = clang
CFLAGS = -Wall -Wextra -O2 -arch arm64 -arch x86_64 -mmacosx-version-min=11.0

# The binary doesn't need Foundation framework - pure C
LDFLAGS =

TARGET = osbx-standalone
SOURCES = main.c

.PHONY: all clean install test sign

all: $(TARGET)

$(TARGET): $(SOURCES)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@echo "Built $(TARGET)"
	@echo ""
	@echo "Usage:"
	@echo "  ./$(TARGET) --help"
	@echo ""
	@echo "To sign with app entitlements:"
	@echo "  ./sign-with-entitlements.sh /path/to/App.app"

clean:
	rm -f $(TARGET)
	rm -f *.o
	rm -f /tmp/osbx-*.json /tmp/osbx-*.txt

# Install to /usr/local/bin (requires sudo)
install: $(TARGET)
	install -m 755 $(TARGET) /usr/local/bin/
	@echo "Installed to /usr/local/bin/$(TARGET)"

# Ad-hoc sign for local testing
sign: $(TARGET)
	codesign -s - --force $(TARGET)
	@echo "Ad-hoc signed $(TARGET)"

# Test with default profile
test: $(TARGET)
	@echo "=== Testing with default (restrictive) profile ==="
	./$(TARGET) --json | head -30
	@echo ""
	@echo "=== Testing with permissive profile ==="
	./$(TARGET) --profile sandbox_profiles/permissive.sb --json | head -30

# Test sandbox_check mode (no actual fs access)
test-sandbox-only: $(TARGET)
	@echo "=== Testing sandbox_check() mode ==="
	./$(TARGET) --sandbox-only --json

# Run without applying sandbox (for comparison)
test-no-sandbox: $(TARGET)
	@echo "=== Testing without sandbox ==="
	./$(TARGET) --no-sandbox --json | head -30

help:
	@echo "Targets:"
	@echo "  all              Build osbx-standalone"
	@echo "  clean            Remove built files"
	@echo "  install          Install to /usr/local/bin"
	@echo "  sign             Ad-hoc sign for local testing"
	@echo "  test             Run basic tests"
	@echo "  test-sandbox-only  Test sandbox_check mode"
	@echo "  test-no-sandbox  Test without sandbox"
	@echo ""
	@echo "To use with a specific app's sandbox:"
	@echo "  ./sign-with-entitlements.sh /Applications/Safari.app"
	@echo "  ./$(TARGET) --no-sandbox /tmp /var ~/Documents"
