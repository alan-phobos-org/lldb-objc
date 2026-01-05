# TODO

## Scan shared cache for static classes

E.g. `[NSDDate distancePast]`

## Better Integration Testing

Should be run rather than just unit tests?

## Did you mean?

```
error: Invalid receiver 'NSDate'. For instance methods, use $variable, $register, or hex address.
(lldb) ocall [NSDate distantPast]
```

Should say did you mean [NSDate distantPast] based on sel matching