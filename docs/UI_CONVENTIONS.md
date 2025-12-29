# UI Conventions

## Color Scheme
- `\033[90m` - Dim gray (secondary info)
- `\033[0m` - Reset

## Principle
**Primary info** (class name, property name) in normal text.
**Secondary info** (types, attributes, hierarchy) in dim gray.

## Examples
```python
# Class hierarchy
print(f"  {class_name} \033[90m→ {hierarchy}\033[0m")

# Properties
print(f"    {prop_name} \033[90m{type_str} ({attrs})\033[0m")

# Instance variables
print(f"    {ivar_name} \033[90m{ivar_type}\033[0m")
```
