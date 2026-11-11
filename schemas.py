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
