"""Root resolution, excludes, and the source-file walk.

Every path stored in the index is a root-relative POSIX string.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Union

from .errors import CartoError
from .settings import Settings

DEFAULT_EXCLUDES = frozenset(
    ".git .hg .svn node_modules __pycache__ .venv venv env dist build out target vendor "
    ".next .nuxt .turbo .mypy_cache .pytest_cache .ruff_cache .tox .idea .vscode coverage "
    ".coverage site-packages bower_components Pods .terraform".split()
)

EXTENSIONS = frozenset(
    ".py .pyi .js .jsx .mjs .cjs .ts .tsx .go .rs .java .kt .kts .c .h .cc .cpp .hpp .cs "
    ".rb .php .swift .scala .lua .sh .bash .zsh".split()
)


@dataclass
class WalkState:
    """Facts the walk learned that the caller needs in its report."""

    truncated: bool = False


def resolve_root(path: Union[str, Path]) -> Path:
    """Expand and resolve *path*, which must be an existing directory.

    Raises:
        CartoError: when the path does not exist or is not a directory.
    """
    try:
        root = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError) as exc:
        raise CartoError(f"not a directory: {path}") from exc
    if not root.is_dir():
        raise CartoError(f"not a directory: {path}")
    return root


def rel_posix(root: Path, path: Path) -> str:
    """Root-relative POSIX path, the only spelling stored in the index."""
    return path.relative_to(root).as_posix()


_ROOT_MARKERS = (".git", "pyproject.toml", "package.json", "go.mod")


def detect_root(start: Path) -> Path:
    """Walk up from *start* to the first directory holding a project marker.

    Returns *start* unchanged when no marker is found within 12 levels.
    """
    start = Path(start).expanduser().resolve()
    current = start
    for _ in range(12):
        if any((current / marker).exists() for marker in _ROOT_MARKERS):
            return current
        if current.parent == current:
            break
        current = current.parent
    return start


def iter_source_files(
    root: Path, settings: Settings, state: WalkState | None = None
) -> Iterator[Path]:
    """Yield candidate source files under *root*, honouring excludes, extensions and caps.

    Prunes dotted directories and excluded names, skips symlinks and files larger
    than ``max_file_kb``, and stops after ``max_files`` with ``state.truncated`` set.
    """
    state = state if state is not None else WalkState()
    root = Path(root)
    excluded = set(DEFAULT_EXCLUDES) | set(settings.excludes)
    max_bytes = settings.max_file_kb * 1024
    yielded = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in excluded
            and not os.path.islink(os.path.join(dirpath, name))
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > max_bytes:
                continue
            yield path
            yielded += 1
            if yielded >= settings.max_files:
                state.truncated = True
                return
