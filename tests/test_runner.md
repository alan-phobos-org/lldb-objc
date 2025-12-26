# Testing ofind Command

## Setup

1. Start an app with LLDB that has IDSService available (any macOS/iOS app using IDS)
2. Break somewhere in the app (e.g., `br set -n main` then run)
3. Load the script:
   ```
   command script import /Users/alan/rc/lldb-objc/objc_find.py
   ```

## Test Cases for IDSService

### Test 1: List All Selectors
```
ofind IDSService
```
**Expected:** Should list all instance and class methods in IDSService

### Test 2: Find 'serviceIdentifier' Selector
```
ofind IDSService serviceIdentifier
```
**Expected:** Should find and display the `serviceIdentifier` method (likely an instance method)

### Test 3: Find '_internal' Selector
```
ofind IDSService _internal
```
**Expected:** Should find and display the `_internal` property/method (private ivar accessor)

### Test 4: Pattern Match - 'service'
```
ofind IDSService service
```
**Expected:** Should display all methods containing "service" in their name

## Debugging Tips

If the command fails:
- Check that the process is stopped: `process status`
- Verify IDSService exists: `expr (Class)NSClassFromString(@"IDSService")`
- Try a simpler class first: `ofind NSString length`

## Expected Selectors in IDSService

Based on typical IDS framework patterns, we expect to find:
- `serviceIdentifier` - instance method returning the service identifier
- `_internal` - private ivar accessor
- Various init/dealloc methods
- Delegate and callback methods
