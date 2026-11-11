"""SQLite schema and the queries the rest of the plugin needs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from .languages import Ref, Symbol

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
  path         TEXT PRIMARY KEY,
  lang         TEXT NOT NULL,
  size         INTEGER NOT NULL,
  mtime_ns     INTEGER NOT NULL,
  digest       TEXT NOT NULL,
  lines        INTEGER NOT NULL,
  symbol_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_files_lang ON files(lang);

CREATE TABLE IF NOT EXISTS symbols (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  path       TEXT NOT NULL,
  name       TEXT NOT NULL,
  qualname   TEXT NOT NULL DEFAULT '',
  kind       TEXT NOT NULL,
  lineno     INTEGER NOT NULL,
  end_lineno INTEGER NOT NULL,
  signature  TEXT NOT NULL DEFAULT '',
  parent     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_symbols_name ON symbols(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_symbols_path ON symbols(path);

CREATE TABLE IF NOT EXISTS refs (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  path    TEXT NOT NULL,
  name    TEXT NOT NULL,
  lineno  INTEGER NOT NULL,
  col     INTEGER NOT NULL,
  kind    TEXT NOT NULL DEFAULT 'name',
  snippet TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_refs_name ON refs(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_refs_path ON refs(path);
"""

def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so ``_work`` matches only itself."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Store:
    """One SQLite index for one repository root."""

    def __init__(self, db_path: Path | str, root: Path):
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-65536")
        self._conn.execute("PRAGMA temp_store=MEMORY")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def sync_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA user_version=1")

    def begin_bulk(self) -> None:
        """Drop the random-order name indexes for a fresh build; ``end_bulk`` rebuilds them."""
        with self._conn:
            self._conn.execute("PRAGMA synchronous=OFF")
            self._conn.execute("DROP INDEX IF EXISTS ix_symbols_name")
            self._conn.execute("DROP INDEX IF EXISTS ix_refs_name")

    def end_bulk(self) -> None:
        with self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_symbols_name ON symbols(name COLLATE NOCASE)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_refs_name ON refs(name COLLATE NOCASE)"
            )
            self._conn.execute("PRAGMA synchronous=NORMAL")

    # -- meta ---------------------------------------------------------------

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        """Return one ``meta`` value, or *default*."""
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def meta_set(self, key: str, value: object) -> None:
        """Upsert one ``meta`` value as text."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    # -- files --------------------------------------------------------------

    def file_row(self, path: str) -> tuple[int, int] | None:
        """Return ``(size, mtime_ns)`` for an indexed file, or None."""
        row = self._conn.execute(
            "SELECT size, mtime_ns FROM files WHERE path = ?", (path,)
        ).fetchone()
        return (row["size"], row["mtime_ns"]) if row else None

    def replace_file(
        self,
        path: str,
        lang: str,
        size: int,
        mtime_ns: int,
        digest: str,
        lines: int,
        symbols: Sequence[Symbol],
        refs: Sequence[Ref],
        commit: bool = True,
    ) -> None:
        """Replace every row for *path*: no stale symbols or refs survive.

        ``commit=False`` keeps the connection's transaction open (wrapped in a
        savepoint so one bad file cannot poison the batch); ``sync`` batches to
        avoid one fsync per file on large trees.
        """
        if commit:
            with self._conn:
                self._write_file_rows(path, lang, size, mtime_ns, digest, lines, symbols, refs)
            return
        self._conn.execute("SAVEPOINT replace_file")
        try:
            self._write_file_rows(path, lang, size, mtime_ns, digest, lines, symbols, refs)
        except BaseException:
            self._conn.execute("ROLLBACK TO replace_file")
            self._conn.execute("RELEASE replace_file")
            raise
        self._conn.execute("RELEASE replace_file")

    def _write_file_rows(
        self,
        path: str,
        lang: str,
        size: int,
        mtime_ns: int,
        digest: str,
        lines: int,
        symbols: Sequence[Symbol],
        refs: Sequence[Ref],
    ) -> None:
        self._conn.execute("DELETE FROM symbols WHERE path = ?", (path,))
        self._conn.execute("DELETE FROM refs WHERE path = ?", (path,))
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.execute(
            "INSERT INTO files(path, lang, size, mtime_ns, digest, lines, symbol_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (path, lang, size, mtime_ns, digest, lines, len(symbols)),
        )
        self._conn.executemany(
            "INSERT INTO symbols(path, name, qualname, kind, lineno, end_lineno, signature, parent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (s.path, s.name, s.qualname, s.kind, s.lineno, s.end_lineno, s.signature, s.parent)
                for s in symbols
            ],
        )
        self._conn.executemany(
            "INSERT INTO refs(path, name, lineno, col, kind, snippet) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.path, r.name, r.lineno, r.col, r.kind, r.snippet) for r in refs],
        )

    def commit(self) -> None:
        """Commit the open batch started by ``replace_file(commit=False)``."""
        self._conn.commit()

    def delete_file(self, path: str) -> None:
        """Remove a file and every symbol/reference row that belongs to it."""
        with self._conn:
            self._conn.execute("DELETE FROM symbols WHERE path = ?", (path,))
            self._conn.execute("DELETE FROM refs WHERE path = ?", (path,))
            self._conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def all_paths(self) -> set[str]:
        """Every indexed path, for deletion detection."""
        return {row["path"] for row in self._conn.execute("SELECT path FROM files")}

    # -- symbols and refs ---------------------------------------------------

    def definitions(
        self,
        name: str,
        limit: int = 50,
        like: str | None = None,
        kind: str | None = None,
        mode: str = "exact",
    ) -> list[dict]:
        """Definitions matching *name* by exact, prefix or fuzzy mode."""
        clauses: list[str] = []
        params: list[object] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if like is not None:
            clauses.append("name LIKE ? COLLATE NOCASE")
            params.append(like)
        elif mode == "exact":
            clauses.append("name = ? COLLATE NOCASE")
            params.append(name)
        elif mode == "prefix":
            clauses.append("name LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(_escape_like(name) + "%")
        elif mode == "fuzzy":
            clauses.append("name LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append("%" + _escape_like(name) + "%")
        else:
            raise ValueError(f"unknown mode: {mode}")
        sql = "SELECT * FROM symbols"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY length(name), path, lineno LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self._conn.execute(sql, params)]

    def references(
        self, name: str, limit: int | None = 100, include_attributes: bool = True
    ) -> list[dict]:
        """References to *name*, optionally excluding attribute accesses."""
        sql = "SELECT * FROM refs WHERE name = ? COLLATE NOCASE"
        params: list[object] = [name]
        if not include_attributes:
            sql += " AND kind != 'attr'"
        sql += " ORDER BY path, lineno, col"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(row) for row in self._conn.execute(sql, params)]

    def non_python_files(self) -> list[tuple[str, str]]:
        """``(path, lang)`` for indexed non-Python files, ordered by path."""
        return [
            (row["path"], row["lang"])
            for row in self._conn.execute(
                "SELECT path, lang FROM files WHERE lang != 'python' ORDER BY path"
            )
        ]

    def has_symbol(self, name: str) -> bool:
        """Case-insensitive check that a definition of *name* exists."""
        row = self._conn.execute(
            "SELECT 1 FROM symbols WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
        ).fetchone()
        return row is not None

    def python_definition_paths(self, name: str) -> list[str]:
        """Distinct ``.py`` files defining *name*."""
        return [
            row["path"]
            for row in self._conn.execute(
                "SELECT DISTINCT path FROM symbols "
                "WHERE name = ? COLLATE NOCASE AND path LIKE '%.py' ORDER BY path",
                (name,),
            )
        ]

    def python_files(self) -> list[str]:
        """Every indexed Python file, ordered by path."""
        return [
            row["path"]
            for row in self._conn.execute(
                "SELECT path FROM files WHERE lang = 'python' ORDER BY path"
            )
        ]

    def outline_rows(self, subpath: str | None = None) -> list[dict]:
        """Symbols joined with their file's line count, ordered for rendering."""
        sql = (
            "SELECT s.path, s.name, s.qualname, s.kind, s.lineno, s.end_lineno, s.signature, "
            "s.parent, f.lines AS file_lines, f.symbol_count "
            "FROM symbols s JOIN files f ON f.path = s.path"
        )
        params: list[object] = []
        if subpath:
            normalized = subpath.replace("\\", "/").strip("/")
            sql += " WHERE s.path = ? OR s.path LIKE ?"
            params.extend([normalized, normalized + "/%"])
        sql += " ORDER BY s.path, s.lineno"
        return [dict(row) for row in self._conn.execute(sql, params)]

    def symbols_for_path(self, path: str) -> list[dict]:
        """All symbols of one file, in source order."""
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM symbols WHERE path = ? ORDER BY lineno", (path,)
            )
        ]

    def counts(self) -> dict:
        """Row counts for files, symbols and refs."""
        def count(table: str) -> int:
            return int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

        return {"files": count("files"), "symbols": count("symbols"), "refs": count("refs")}

    def files_by_lang(self) -> dict[str, int]:
        """File count per language."""
        return {
            row["lang"]: row["n"]
            for row in self._conn.execute("SELECT lang, COUNT(*) AS n FROM files GROUP BY lang")
        }

    def symbol_kinds(self) -> dict[str, int]:
        """Symbol count per kind."""
        return {
            row["kind"]: row["n"]
            for row in self._conn.execute("SELECT kind, COUNT(*) AS n FROM symbols GROUP BY kind")
        }
