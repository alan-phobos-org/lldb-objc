# Feature Roadmap

## Completed

| Command | Description |
|---------|-------------|
| `obrk` | Set breakpoints on ObjC methods |
| `osel` | Find methods in a class |
| `ocls` | Find classes by pattern (optimized + hierarchy + ivars/properties) |
| `ocall` | Call ObjC methods from CLI |
| `owatch` | Auto-logging breakpoints |
| `oprotos` | Protocol conformance finder |

## Next Up

### Wildcard `osel`
Cross-class method search:
```bash
osel IDS* send*
# -[IDSService sendMessage:]
# -[IDSConnection sendAck:]
# Total: 4 methods in 3 classes
```

## Future Ideas

| Command | Description |
|---------|-------------|
| `oheap` | Find live instances on heap via malloc zone introspection |
| `ocat` | Category method inspector / collision detector |
| `oswizzle` | Runtime method swizzling |
| `oblock` | Block inspector |

## Known Issues

### Bitfield Position Tracking
The `--ivars` output shows bitfields with bit width but not position within the byte. The runtime's `ivar_getOffset()` only returns byte offset, not bit position.

## Performance Notes

Batch size **35** is optimal. Key optimizations:
- Bulk `ReadMemory()` instead of per-item expressions
- Objective-C blocks for compound expressions
- Per-process caching (<0.01s on subsequent queries)
