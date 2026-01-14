# HelloWorld-Sandboxed

Sandboxed version of HelloWorld for testing the `osbx` sandbox scanner command.

## Sandbox Profile

This binary uses `sandbox_init()` to opt into a restrictive sandbox:

- **File Write**: Only `/tmp`, `/private/tmp`, `/dev/null`, `/dev/zero`
- **File Read**: Allowed (needed for runtime)
- **Network**: Denied
- **Process**: Fork/exec allowed

## Building

```bash
make
```

## Testing with osbx

```bash
# From project root
python tests/test_osbx_sandboxed.py
```

## Expected osbx Results

When running `osbx` against this binary, it should report:

- **Writable**: `/tmp`, `/private/tmp`, `/dev/null`, `/dev/zero`
- **Non-Writable**: Everything else (home directory, ~/Documents, etc.)
- **Sandbox Status**: Active (detected via sandbox_check)

This allows validation that osbx correctly identifies the sandbox restrictions.
