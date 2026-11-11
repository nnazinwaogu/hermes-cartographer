"""Core objects for the fixture project."""

DEFAULT_LIMIT = 3


class Engine:
    """Runs work units."""

    mode = "fast"

    def __init__(self, name: str, limit: int = DEFAULT_LIMIT):
        self.name = name
        self.limit = limit

    def run(self, *units, retries: int = 1, **options):
        return [self._work(unit, retries=retries, **options) for unit in units]

    def _work(self, unit, retries=1, **options):
        return (unit, retries, options)
