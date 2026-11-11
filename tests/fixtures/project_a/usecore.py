"""References the core objects."""

from .core import DEFAULT_LIMIT, Engine


def run_once():
    engine = Engine("once", limit=DEFAULT_LIMIT)
    return engine.run(1)
