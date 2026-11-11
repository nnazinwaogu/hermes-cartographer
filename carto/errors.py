"""The single exception type the library raises to the plugin layer."""

from __future__ import annotations


class CartoError(Exception):
    """A user-actionable failure: bad root, refused rename, unreadable index."""
