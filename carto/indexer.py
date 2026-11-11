"""Incremental index sync and store opening."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__ as carto_version
from .errors import CartoError
from .languages import FileScan, detect_lang, scan_generic, scan_python
from .paths import WalkState, iter_source_files, rel_posix, resolve_root
from .settings import Settings
from .store import Store

logger = logging.getLogger(__name__)

PLUGIN_NAME = "hermes-cartographer"


@dataclass
class IndexReport:
    root: Path
    db: Path
    scanned: int
    indexed: int
    removed: int
    symbols: int
    refs: int
    duration_ms: int
    truncated: bool


def db_path_for(root: Path) -> Path:
    """One DB per root under ``plugin-data/hermes-cartographer/``.

    Imported lazily so the library stays usable without Hermes installed.
    """
    digest = hashlib.sha1(str(Path(root)).encode("utf-8")).hexdigest()[:12]
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ImportError as exc:  # pragma: no cover - exercised only outside Hermes
        raise CartoError(
            "Hermes plugin storage is unavailable; run this inside Hermes "
            "(`hermes carto index <path>`) or pass an explicit index path"
        ) from exc
    return plugin_data_dir(PLUGIN_NAME) / f"index-{digest}.db"


def _read_bytes(path: Path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _scan_file(lang: str, rel_path: str, text: str) -> FileScan:
    if lang == "python":
        return scan_python(rel_path, text)
    return scan_generic(rel_path, text, lang)


def sync(
    root: Path,
    settings: Settings,
    db_path: Path | None = None,
    force: bool = False,
    time_budget_ms: int | None = None,
) -> IndexReport:
    """Walk *root* and bring the index up to date.

    Unchanged files are skipped on ``(size, mtime_ns)`` without reading their
    contents. A per-file failure is logged and the sync continues. When
    *time_budget_ms* expires the walk stops and the report says ``truncated``;
    pruning is skipped in that case, because unwalked files are not deletions.
    """
    root = resolve_root(root)
    db = Path(db_path) if db_path is not None else db_path_for(root)
    started = time.monotonic()
    deadline = started + time_budget_ms / 1000.0 if time_budget_ms else None

    store = Store(db, root)
    store.sync_schema()
    state = WalkState()
    walked: set[str] = set()
    scanned = indexed = 0

    try:
        for path in iter_source_files(root, settings, state):
            if deadline is not None and time.monotonic() >= deadline:
                state.truncated = True
                break
            rel_path = rel_posix(root, path)
            walked.add(rel_path)
            scanned += 1
            try:
                stat = path.stat()
                if not force and store.file_row(rel_path) == (stat.st_size, stat.st_mtime_ns):
                    continue
                raw = _read_bytes(path)
                text = raw.decode("utf-8", errors="replace")
                lang = detect_lang(rel_path)
                scan = _scan_file(lang, rel_path, text)
                store.replace_file(
                    rel_path,
                    lang,
                    stat.st_size,
                    stat.st_mtime_ns,
                    hashlib.sha1(raw).hexdigest(),
                    scan.lines,
                    scan.symbols,
                    scan.refs,
                )
                indexed += 1
            except Exception:  # noqa: BLE001 - one bad file must not abort the sync
                state.unreadable += 1
                logger.debug("cartographer: skipped %s", rel_path, exc_info=True)

        removed = 0
        if not state.truncated:
            stale = store.all_paths() - walked
            for path in stale:
                store.delete_file(path)
            removed = len(stale)

        counts = store.counts()
        duration_ms = int((time.monotonic() - started) * 1000)
        for key, value in (
            ("root", str(root)),
            ("last_index_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ("last_index_ms", duration_ms),
            ("hermes_carto_version", carto_version),
            ("files", counts["files"]),
            ("symbols", counts["symbols"]),
            ("refs", counts["refs"]),
        ):
            store.meta_set(key, value)

        return IndexReport(
            root=root,
            db=db,
            scanned=scanned,
            indexed=indexed,
            removed=removed,
            symbols=counts["symbols"],
            refs=counts["refs"],
            duration_ms=duration_ms,
            truncated=state.truncated,
        )
    finally:
        store.close()


def _is_stale(store: Store, refresh_after_s: float) -> bool:
    raw = store.meta_get("last_index_at")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() >= refresh_after_s


def open_store(
    root: Path,
    settings: Settings,
    refresh_after_s: float = 0,
    time_budget_ms: int | None = None,
) -> Store:
    """Return an open, schema-ready Store, syncing first when the index is stale.

    ``refresh_after_s=0`` (the tools' choice) always runs the stat-only refresh.
    ``time_budget_ms`` bounds the walk so the hook can index a fresh root without
    blowing its per-turn budget.
    """
    root = resolve_root(root)
    db = db_path_for(root)
    if db.exists():
        store = Store(db, root)
        store.sync_schema()
        if not _is_stale(store, refresh_after_s):
            return store
        store.close()

    sync(root, settings, db_path=db, time_budget_ms=time_budget_ms)
    store = Store(db, root)
    store.sync_schema()
    return store


def stats(root: Path, settings: Settings) -> dict:
    """Report what the index holds without refreshing it."""
    root = resolve_root(root)
    db = db_path_for(root)
    data = {
        "root": str(root),
        "db": str(db),
        "indexed": db.exists(),
        "files": 0,
        "symbols": 0,
        "refs": 0,
        "languages": {},
        "kinds": {},
        "last_index_at": None,
        "last_index_ms": None,
        "db_bytes": 0,
    }
    if not data["indexed"]:
        return data

    store = Store(db, root)
    store.sync_schema()
    try:
        counts = store.counts()
        return {
            **data,
            "files": counts["files"],
            "symbols": counts["symbols"],
            "refs": counts["refs"],
            "languages": store.files_by_lang(),
            "kinds": store.symbol_kinds(),
            "last_index_at": store.meta_get("last_index_at"),
            "last_index_ms": store.meta_get("last_index_ms"),
            "db_bytes": db.stat().st_size,
        }
    finally:
        store.close()
