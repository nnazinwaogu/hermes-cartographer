"""JSON schemas for the Cartographer tools."""

from __future__ import annotations

CODE_MAP = {
    "type": "object",
    "description": (
        "Show a compact symbol outline (classes, functions, methods with signatures) for a "
        "codebase, path-relative and token-budgeted. Use this FIRST on an unfamiliar repo "
        "instead of reading whole files. Path defaults to the current workspace."
    ),
    "properties": {
        "path": {
            "type": "string",
            "description": "Repository root to operate on. Defaults to the current workspace.",
        },
        "budget": {
            "type": "integer",
            "description": "Maximum characters in the returned map. Defaults to the plugin's default_map_budget.",
        },
        "subpath": {
            "type": "string",
            "description": "Limit the map to one file or subdirectory of the root.",
        },
    },
    "additionalProperties": False,
    "required": [],
}

SYMBOL_FIND = {
    "type": "object",
    "description": (
        "Find where a symbol is defined: file, line, kind and signature. Use instead of grep "
        "when you know the name."
    ),
    "properties": {
        "name": {
            "type": "string",
            "description": "Symbol name to find. With mode=exact the full name; prefix and fuzzy match on it.",
        },
        "kind": {
            "type": "string",
            "enum": ["class", "function", "method", "constant", "type"],
            "description": "Only return definitions of this kind.",
        },
        "mode": {
            "type": "string",
            "enum": ["exact", "prefix", "fuzzy"],
            "description": "Matching mode. Defaults to exact; use prefix or fuzzy when the exact name is unknown.",
        },
        "path": {
            "type": "string",
            "description": "Repository root to operate on. Defaults to the current workspace.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum definitions to return. Defaults to 50.",
        },
    },
    "additionalProperties": False,
    "required": ["name"],
}

SYMBOL_REFS = {
    "type": "object",
    "description": (
        "List every indexed reference to a symbol with file:line and the source line. Python "
        "references are AST-precise; other languages are scanned on disk."
    ),
    "properties": {
        "name": {
            "type": "string",
            "description": "Name whose references to list.",
        },
        "include_attributes": {
            "type": "boolean",
            "description": "Include attribute accesses such as obj.name. Defaults to false; Python references are AST-precise.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum references to return. Defaults to 100.",
        },
        "path": {
            "type": "string",
            "description": "Repository root to operate on. Defaults to the current workspace.",
        },
    },
    "additionalProperties": False,
    "required": ["name"],
}

SYMBOL_RENAME = {
    "type": "object",
    "description": (
        "Rename a Python symbol across the whole repo by editing only real identifier "
        "occurrences (AST-verified, syntax-checked before writing). Method renames always edit "
        "`self.old(...)` call sites. Returns a unified diff. Defaults to dry_run=true; set false "
        "to apply. Other languages are refused."
    ),
    "properties": {
        "old": {
            "type": "string",
            "description": "Existing Python symbol name to rename.",
        },
        "new": {
            "type": "string",
            "description": "Replacement identifier. Must not be a keyword, builtin or existing symbol.",
        },
        "path": {
            "type": "string",
            "description": "Repository root to operate on. Defaults to the current workspace.",
        },
        "dry_run": {
            "type": "boolean",
            "description": "Return the diff without writing. Defaults to true; set false to apply.",
        },
        "include_attributes": {
            "type": "boolean",
            "description": "Also rename attribute accesses to non-method symbols. Method call sites are always edited.",
        },
    },
    "additionalProperties": False,
    "required": ["old", "new"],
}
