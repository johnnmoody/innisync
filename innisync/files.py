"""InniSync's own files on this computer (settings, caches, state). Writes go to a temporary file beside the real one
and are renamed into place, so a crash or a full disk mid-write never leaves a half-written settings file."""
import json
import os


def read_json(path):
    """The file's JSON. Raises OSError (missing) or ValueError (damaged) for the caller's fallback."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
    os.replace(tmp, path)
