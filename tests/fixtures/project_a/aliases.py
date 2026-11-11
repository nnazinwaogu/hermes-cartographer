"""Import aliases, used by the rename tests."""

from .helpers import build as make
from .core import Engine


def make_engine() -> Engine:
    return Engine(make.__name__)
