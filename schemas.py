"""JSON schemas for the Cartographer tools."""

from __future__ import annotations

CODE_MAP = {
    "type": "object",
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
