"""Smart playlists, iTunes-style: "Match all/any of the following rules", optional "Limit to N songs selected by ...".

Jellyfin has no rule-based playlists, so the definitions live in Application Support/smart_playlists.json and are
worked out against the library here. The server lists them with the Jellyfin playlists (ids "smart-..."), so the
sidebar, the Music tab and sync treat them like any other playlist and they update as the library changes.
"""
import datetime
import json
import os
import random
import uuid

from . import files, sync

PATH = os.path.join(sync.APP_DIR, "smart_playlists.json")

# field -> (label, type). Song keys come from jellyfin.Jellyfin.songs().
FIELDS = {
    "name": ("Name", "text"), "artist": ("Artist", "text"), "album": ("Album", "text"), "genre": ("Genre", "text"),
    "container": ("Kind", "text"), "year": ("Year", "number"), "duration": ("Time (seconds)", "number"),
    "plays": ("Plays", "number"), "added": ("Date Added", "date"), "lastPlayed": ("Last Played", "date"),
    "favorite": ("Favorite", "bool"),
}
OPS = {
    "text": ["contains", "does not contain", "is", "is not", "starts with", "ends with"],
    "number": ["is", "is not", "is greater than", "is less than", "is in the range"],
    "date": ["is in the last", "is not in the last", "is before", "is after"],
    "bool": ["is true", "is false"],
}
ORDERS = ["random", "name", "artist", "album", "most played", "least played", "most recently added",
          "most recently played", "least recently played"]
UNITS = ["songs", "minutes", "hours", "GB"]


def load():
    try:
        return files.read_json(PATH)
    except (OSError, ValueError):
        return []


def _write(defs):
    files.write_json(PATH, defs, indent=1)


def validate(d):
    """A clean definition, or ValueError saying what's wrong."""
    name = (d.get("name") or "").strip()
    if not name:
        raise ValueError("Give the smart playlist a name")
    rules = []
    for r in d.get("rules") or []:
        field = r.get("field")
        if field not in FIELDS:
            raise ValueError(f"Unknown field {field}")
        kind = FIELDS[field][1]
        if r.get("op") not in OPS[kind]:
            raise ValueError(f"“{r.get('op')}” doesn't work with {FIELDS[field][0]}")
        rule = {"field": field, "op": r["op"]}
        if kind == "number" or r["op"] in ("is in the last", "is not in the last"):
            try:
                rule["value"] = float(r.get("value"))
                if r["op"] == "is in the range":
                    rule["value2"] = float(r.get("value2"))
            except (TypeError, ValueError):
                raise ValueError(f"{FIELDS[field][0]} needs a number")
            if r["op"] in ("is in the last", "is not in the last"):
                rule["unit"] = r.get("unit") if r.get("unit") in ("days", "weeks", "months") else "days"
        elif kind == "date":
            try:
                datetime.date.fromisoformat(r.get("value") or "")
            except ValueError:
                raise ValueError(f"{FIELDS[field][0]} needs a date")
            rule["value"] = r["value"]
        elif kind == "text":
            rule["value"] = str(r.get("value") or "")
        rules.append(rule)
    lim = d.get("limit") or {}
    limit = {"on": bool(lim.get("on")), "count": max(float(lim.get("count") or 25), 0.1),
             "unit": lim.get("unit") if lim.get("unit") in UNITS else "songs",
             "by": lim.get("by") if lim.get("by") in ORDERS else "random"}
    return {"id": d.get("id") or "smart-" + uuid.uuid4().hex[:12], "name": name,
            "match": "any" if d.get("match") == "any" else "all", "rules": rules, "limit": limit}


def save(d):
    d = validate(d)
    defs = [x for x in load() if x["id"] != d["id"]] + [d]
    _write(sorted(defs, key=lambda x: x["name"].lower()))
    return d


def delete(pid):
    _write([x for x in load() if x["id"] != pid])


def _date(s):
    if not s:
        return None
    return datetime.datetime.fromisoformat(s[:19]).replace(tzinfo=datetime.timezone.utc)


def _test(song, r, now):
    field, op, kind = r["field"], r["op"], FIELDS[r["field"]][1]
    if kind == "text":
        if field == "artist":
            vals = {song.get("artist") or "", song.get("albumArtist") or "", *song.get("artists", [])}
        elif field == "genre":
            vals = set(song.get("genres") or []) or {""}
        else:
            vals = {str(song.get(field) or "")}
        v = r["value"].casefold()
        vals = {x.casefold() for x in vals}
        hit = {"contains": lambda x: v in x, "does not contain": lambda x: v not in x, "is": lambda x: x == v,
               "is not": lambda x: x != v, "starts with": lambda x: x.startswith(v), "ends with": lambda x: x.endswith(v)}[op]
        # "does not contain" / "is not" must hold for every name the song goes by; the rest for any
        return all(map(hit, vals)) if op in ("does not contain", "is not") else any(map(hit, vals))
    if kind == "number":
        x, v = song.get(field) or 0, r["value"]
        if op == "is in the range":
            return min(v, r["value2"]) <= x <= max(v, r["value2"])
        return {"is": x == v, "is not": x != v, "is greater than": x > v, "is less than": x < v}[op]
    if kind == "date":
        x = _date(song.get(field))
        if op in ("is in the last", "is not in the last"):
            days = r["value"] * {"days": 1, "weeks": 7, "months": 30}[r["unit"]]
            inside = bool(x) and x >= now - datetime.timedelta(days=days)
            return inside if op == "is in the last" else not inside
        if not x:
            return False
        day = datetime.date.fromisoformat(r["value"])
        return x.date() < day if op == "is before" else x.date() > day
    return bool(song.get(field)) == (op == "is true")


def _last(v):
    """Untagged sorts after everything else, like the song list."""
    return (not v, v)


def _order(songs, by, seed):
    if by == "random":
        songs = sorted(songs, key=lambda s: s["id"])
        random.Random(seed).shuffle(songs)   # same pick until the rules change, so syncs don't churn
        return songs
    key, rev = {
        "name": (lambda s: _last((s["name"] or "").casefold()), False),
        "artist": (lambda s: (_last((s["albumArtist"] or s["artist"] or "").casefold()), s["album"], s.get("disc") or 0, s.get("track") or 0), False),
        "album": (lambda s: (_last((s["album"] or "").casefold()), s.get("disc") or 0, s.get("track") or 0), False),
        "most played": (lambda s: s.get("plays") or 0, True), "least played": (lambda s: s.get("plays") or 0, False),
        "most recently added": (lambda s: s.get("added") or "", True),
        "most recently played": (lambda s: s.get("lastPlayed") or "", True),
        "least recently played": (lambda s: s.get("lastPlayed") or "", False),
    }[by]
    return sorted(songs, key=key, reverse=rev)


def evaluate(d, lib):
    """Song ids in playlist order."""
    now = datetime.datetime.now(datetime.timezone.utc)
    test = all if d["match"] == "all" else any
    songs = [s for s in lib.values() if not d["rules"] or test(_test(s, r, now) for r in d["rules"])]
    lim = d["limit"]
    if not lim["on"]:
        return [s["id"] for s in _order(songs, "artist", None)]
    out, total = [], 0
    cap = lim["count"] * {"songs": 1, "minutes": 60, "hours": 3600, "GB": 1e9}[lim["unit"]]
    seed = json.dumps([d["rules"], d["match"], lim])
    for s in _order(songs, lim["by"], seed):
        size = {"songs": 1, "GB": s.get("size") or 0}.get(lim["unit"], s.get("duration") or 0)
        if total + size > cap and (lim["unit"] == "songs" or out):
            if lim["unit"] == "songs":
                break
            continue   # too long for what's left: a shorter song may still fit
        out.append(s["id"])
        total += size
    return out


def playlists(lib):
    """([{id, name, smart: True}], {id: [song ids]}) for every smart playlist."""
    defs = load()
    return [{"id": d["id"], "name": d["name"], "smart": True} for d in defs], {d["id"]: evaluate(d, lib) for d in defs}
