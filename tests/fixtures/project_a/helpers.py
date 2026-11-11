"""Helper functions."""

from .core import Engine

PREFIX = "job"


def build(name: str, engine: Engine = None) -> str:
    def label():
        return f"{PREFIX}:{name}"

    return label()


def describe(engine):
    return engine.name
