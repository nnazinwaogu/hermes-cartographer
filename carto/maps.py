"""Token-budgeted repo map rendering."""

from __future__ import annotations

from pathlib import Path

from .store import Store

_INDENT = "  "


def _symbol_line(row: dict) -> str:
    name = row["name"]
    if row["kind"] == "class":
        return f"class {name}"
    if row["kind"] == "type":
        return f"type {name}"
    if row["kind"] == "constant":
        return name
    return f"def {name}{row['signature']}"


def render_map(
    store: Store, root: Path, budget_chars: int, subpath: str | None = None
) -> tuple[str, dict]:
    """Render the outline, keeping the body inside *budget_chars*.

    The truncation footer is appended outside the budget so the model never
    loses the "there is more here" signal to the cut.
    """
    rows = store.outline_rows(subpath)
    if not rows:
        return (
            f"(no symbols indexed for {root} — run `hermes carto index`)\n",
            {"files": 0, "symbols": 0, "truncated": False},
        )

    total_files = len({row["path"] for row in rows})
    lines: list[str] = []
    used = 0
    shown_files: set[str] = set()
    shown_symbols = 0
    current_path: str | None = None
    truncated = False

    def fits(line: str) -> bool:
        return used + len(line) + 1 <= budget_chars

    for row in rows:
        if row["path"] != current_path:
            header = f"{row['path']}  ({row['file_lines']})"
            if not fits(header):
                truncated = True
                break
            lines.append(header)
            used += len(header) + 1
            current_path = row["path"]

        line = _INDENT * (row["qualname"].count(".") + 1) + _symbol_line(row)
        if not fits(line):
            truncated = True
            break
        lines.append(line)
        used += len(line) + 1
        shown_files.add(row["path"])
        shown_symbols += 1

    if truncated:
        omitted_symbols = len(rows) - shown_symbols
        omitted_files = total_files - len(shown_files)
        footer = (
            f"… +{omitted_symbols} symbols in {omitted_files} files not shown. "
            "Narrow the path or raise map_budget."
        )
        return "\n".join(lines) + "\n" + footer + "\n", {
            "files": len(shown_files),
            "symbols": shown_symbols,
            "truncated": True,
        }

    return "\n".join(lines) + "\n", {
        "files": len(shown_files),
        "symbols": shown_symbols,
        "truncated": False,
    }
