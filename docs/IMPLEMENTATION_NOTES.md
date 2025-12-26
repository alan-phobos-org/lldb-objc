# Implementation Notes for ofind

## Key Design Decisions

### Memory Management
- **Allocate count variable**: We need a pointer to pass to `class_copyMethodList()` to receive the count
- **Free method list**: `class_copyMethodList()` returns a malloc'd array that must be freed
- **Free count variable**: We malloc'd the count variable, so we must free it too

### Method List Iteration
- Method list is an array of `Method` pointers
- Pointer size depends on architecture (use `frame.GetModule().GetAddressByteSize()`)
- Access array elements: `((void **)method_list)[i]`

### String Extraction
- `sel_getName()` returns a C string pointer
- Use `GetSummary()` to get the string value from LLDB
- Summary includes quotes, so strip them: `sel_name.strip('"')`

### Pattern Matching
- Case-insensitive substring match: `pattern.lower() in sel_name.lower()`
- Applied during iteration to reduce output noise
- None pattern means show all methods

## Runtime API Functions Used

```c
// Get methods from a class
Method *class_copyMethodList(Class cls, unsigned int *outCount);

// Get selector from a method
SEL method_getName(Method m);

// Convert selector to string
const char *sel_getName(SEL sel);

// Get metaclass (for class methods)
Class object_getClass(id obj);
```

## Common Pitfalls

### 1. Not Freeing Memory
**Problem**: Memory leaks if we don't free allocated memory
**Solution**: Always free in reverse order of allocation, even on error paths

### 2. Wrong Pointer Arithmetic
**Problem**: Assuming 8-byte pointers on all platforms
**Solution**: Use `frame.GetModule().GetAddressByteSize()` for pointer size

### 3. String Quotes in Summary
**Problem**: `GetSummary()` returns `"string"` with quotes
**Solution**: Strip quotes with `strip('"')`

### 4. Invalid Method Pointers
**Problem**: Some array elements might be null or invalid
**Solution**: Check each pointer before dereferencing

## Debugging Tips

### Enable Verbose Output
Add debug prints to see what's happening:
```python
print(f"DEBUG: method_list_ptr = 0x{method_list_ptr:x}")
print(f"DEBUG: method_count = {method_count}")
print(f"DEBUG: method[{i}] = 0x{method_ptr:x}")
```

### Verify Method List
Check method list manually in LLDB:
```
(lldb) expr (Method *)class_copyMethodList((Class)0x..., (unsigned int *)0x...)
(lldb) expr (SEL)method_getName((Method)0x...)
(lldb) expr (char *)sel_getName((SEL)0x...)
```

### Test with Known Classes
Start with well-known classes:
```
ofind NSString          # Lots of methods, should work
ofind NSObject          # Basic methods
ofind NSArray           # Collection methods
```

## Performance Considerations

### Method Count
- NSString has ~100+ methods
- UIViewController has ~200+ methods
- Some private classes may have 500+ methods

### Memory Usage
- Method list size: `pointer_size * method_count` bytes
- Temporary for the duration of the command
- Always freed before returning

### Speed
- Runtime method enumeration is fast (microseconds)
- Pattern matching is O(n) where n = number of methods
- Sorting adds O(n log n) but improves readability

## Future Enhancements

Potential improvements:
- **Regex patterns**: Support full regex instead of substring
- **Show method signatures**: Display full type encodings
- **Method categories**: Group by category or protocol
- **Inherited methods**: Option to show/hide inherited methods
- **Export to file**: Save method list to a file
- **Interactive mode**: Show method and ask to set breakpoint
- **IMP addresses**: Optionally show implementation addresses
