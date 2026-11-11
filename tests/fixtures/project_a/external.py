"""Uses names defined outside the repository."""

import json


def serialize(payload):
    return json.dumps(payload, sort_keys=True)
