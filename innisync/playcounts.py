"""Play counts from the Y1 back to the music server, the way iTunes picked up an iPod's plays on sync.

InniClassic appends every play to /storage/sdcard0/.scrobbler.log (Audioscrobbler 1.1: artist, album, title,
track, seconds, rating, unix time UTC, mbid) and never clears it, so plays already sent are remembered per Y1 in
Application Support and skipped. Each new play is matched to a library song by title + artist (album breaks ties)
and counted on the music server (Jellyfin POST /UserPlayedItems/{id}?datePlayed=, Subsonic scrobble).

Both servers set the last-played date to whatever date they are given, so a play is never dated before the song's current
last-played date (a newer play on another device would otherwise be pushed back). Plays logged while the Y1's
clock was reset (before 2025) count, but don't move the date.
"""
import datetime
import json
import os

from . import device, sync
from .jellyfin import norm

CLOCK_OK = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)


def state_path(serial):
    return os.path.join(sync.APP_DIR, f"playcounts_{serial}.json")


def load_state(serial):
    try:
        return json.load(open(state_path(serial)))
    except (OSError, ValueError):
        return {"sent": [], "unmatched": []}


def save_state(serial, st):
    os.makedirs(sync.APP_DIR, exist_ok=True)
    tmp = state_path(serial) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_path(serial))


def parse(text):
    """Listened ("L") plays from a scrobbler.log, oldest first."""
    plays = []
    for line in text.replace("\r", "").splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 7 or f[5] != "L" or not f[6].isdigit():
            continue
        plays.append({"artist": f[0], "album": f[1], "title": f[2], "ts": int(f[6])})
    return sorted(plays, key=lambda p: p["ts"])


def key(p):
    return f"{p['ts']}|{p['artist']}|{p['title']}"


def index(lib):
    """{(title, artist): [song]} for every artist name a song goes by."""
    out = {}
    for s in lib.values():
        for a in {s["artist"], s["albumArtist"], *s.get("artists", [])}:
            if a:
                out.setdefault((norm(s["name"]), norm(a)), []).append(s)
    return out


def match(p, idx):
    cands = idx.get((norm(p["title"]), norm(p["artist"])), [])
    if not cands:
        return None
    return next((s for s in cands if norm(s["album"]) == norm(p["album"])), cands[0])


def send(jf, lib, serial, log_text, progress=lambda n, total: None, cancel=lambda: False):
    """Count the log's plays that haven't been sent on the music server. Plays that matched no song are tried again
    each time (the song may have been added since). Returns {"new", "sent", "unmatched"}; "new" counts only plays not
    seen before."""
    st = load_state(serial)
    sent_keys, before = set(st["sent"]), set(st["unmatched"])
    todo = [p for p in parse(log_text) if key(p) not in sent_keys]
    idx = index(lib)
    sent, still, n = 0, [], 0
    try:
        for p in todo:
            if cancel():
                break
            progress(n + 1, len(todo))
            song = match(p, idx)
            if not song:
                still.append(key(p))
                n += 1
                continue
            when = datetime.datetime.fromtimestamp(p["ts"], datetime.timezone.utc)
            last = jf.last_played(song["id"])
            if when < CLOCK_OK:
                when = last or datetime.datetime.now(datetime.timezone.utc)
            elif last and when < last:
                when = last
            jf.mark_played(song["id"], when)
            st["sent"].append(key(p))
            sent += 1
            n += 1
            if sent % 25 == 0:
                save_state(serial, st)
    finally:   # whatever was sent stays recorded, even when the server stops answering partway
        st["unmatched"] = sorted(set(still) | {key(p) for p in todo[n:] if key(p) in before})
        save_state(serial, st)
    return {"new": len([p for p in todo if key(p) not in before]), "sent": sent, "unmatched": len(still)}


def read_log():
    """The Y1's scrobbler.log text, or "" if it has none."""
    if not device.exists(device.SCROBBLER_LOG):
        return ""
    return device.cat_bytes(device.SCROBBLER_LOG).decode("utf-8", "replace")
