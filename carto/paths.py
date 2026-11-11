"""Root resolution and path helpers. All stored paths are root-relative POSIX strings."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from .errors import CartoError


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
