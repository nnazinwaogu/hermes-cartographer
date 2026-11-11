---
name: cartographer
description: Navigate a codebase by symbols instead of reading whole files.
---

# Cartographer

Use this skill when you are in an unfamiliar repository or about to read files
to answer "where is X", "who calls X", or "rename X".

## Order of operations

1. `code_map` — get the file/symbol outline first. Narrow with `subpath` or
   `budget` instead of reading whole trees.
2. `symbol_find` — once you know a name, get its `file:line`, kind and
   signature. Use `mode=prefix` or `mode=fuzzy` when the exact name is unknown.
3. `symbol_refs` — list every call site before editing. Python positions are
   AST-precise; other languages are scanned on disk. Set
   `include_attributes=true` to see `obj.name` accesses.
4. Read only the lines those results name. Do not re-read whole files.

## Rename workflow

1. `symbol_rename` with `old` and `new` — dry run is the default. Read the
   unified diff and the warnings.
2. Warnings mean the tool refused to edit an unreliable span (an import alias,
   `global`/`nonlocal`, `except ... as`, a match pattern). Fix those by hand.
3. Call again with `dry_run=false` to write. Files are rewritten atomically,
   re-parsed first, and re-indexed after.
4. Rename is Python-only. Methods always edit `self.old(...)` call sites;
   other attributes need `include_attributes=true`.

## Truthfulness

The index is incremental and may be stale; the CLI (`hermes carto index`)
rebuilds it. Python is AST-precise. Other languages are definitions-only: no
type inference, no call graph, and rename is refused for them.
