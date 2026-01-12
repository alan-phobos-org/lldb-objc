# Makefile for HelloWorld-Optimised example
# Heavily optimized and stripped binary for testing LLDB command robustness

TARGET = HelloWorld/HelloWorld
SOURCE = HelloWorld/main.m

# Compiler and aggressive optimization flags
CC = clang
CFLAGS = -framework Foundation \
         -fobjc-arc \
         -O3 \
         -DNDEBUG \
         -flto \
         -fno-exceptions \
         -fvisibility=hidden \
         -fvisibility-inlines-hidden \
         -dead_strip

# Build the optimized binary and strip it
$(TARGET): $(SOURCE)
	$(CC) $(CFLAGS) -o $(TARGET) $(SOURCE)
	strip -x $(TARGET)

# Build with debug info (for comparison testing)
debug: $(SOURCE)
	$(CC) -framework Foundation -fobjc-arc -g -o $(TARGET)-debug $(SOURCE)

# Clean build artifacts
clean:
	rm -f $(TARGET) $(TARGET)-debug

# Rebuild from scratch
rebuild: clean $(TARGET)

# Run the binary
run: $(TARGET)
	./$(TARGET)

# Show binary info (useful for verification)
info: $(TARGET)
	@echo "=== File info ==="
	file $(TARGET)
	@echo "\n=== Size ==="
	ls -lh $(TARGET)
	@echo "\n=== Symbols (should be minimal) ==="
	nm $(TARGET) 2>/dev/null | head -20 || echo "No symbols found (expected)"
	@echo "\n=== Objective-C classes (should still work via runtime) ==="
	otool -oV $(TARGET) | grep -A2 "Contents of"

.PHONY: clean rebuild run debug info
