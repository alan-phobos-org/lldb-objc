# Makefile for HelloWorld-Sandboxed example
# This sandboxed Objective-C program is used for testing osbx sandbox detection.
# Uses sandbox_init() to opt into a restrictive sandbox profile:
#   - Write access only to /tmp, /private/tmp, /dev/null, /dev/zero
#   - Network access denied

TARGET = HelloWorld/HelloWorld
SOURCE = HelloWorld/main.m

# Compiler and flags
CC = clang
CFLAGS = -framework Foundation -g -fobjc-arc

# Build the binary
$(TARGET): $(SOURCE)
	$(CC) $(CFLAGS) -o $(TARGET) $(SOURCE)

# Clean build artifacts
clean:
	rm -f $(TARGET)
	rm -rf $(TARGET).dSYM

# Rebuild from scratch
rebuild: clean $(TARGET)

# Run the binary
run: $(TARGET)
	./$(TARGET)

.PHONY: clean rebuild run
