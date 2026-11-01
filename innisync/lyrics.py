"""Timed lyrics from LRCLIB (lrclib.net, or a self-hosted copy: the server is open source).

API, read from the server source (tranxuanthang/lrclib, server/src/routes/get_lyrics_by_metadata.rs):
GET /api/get?track_name=&artist_name=&album_name=&duration= -> 200 {syncedLyrics, plainLyrics, instrumental, ...},
404 when it has no match, 503 when overloaded. Clients name themselves with the Lrclib-Client header.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVER = "https://lrclib.net"
CLIENT = "InniSync"


class Unavailable(Exception):
    """LRCLIB couldn't answer (down, overloaded, no network): ask again on the next sync."""


def synced(song, server=DEFAULT_SERVER):
    """The song's timed lyrics as .lrc text, or None if LRCLIB has none. Raises Unavailable."""
    if not song.get("name") or not song.get("artist"):
        return None
    params = {"track_name": song["name"], "artist_name": song["artist"]}
    if song.get("album"):
        params["album_name"] = song["album"]
    if song.get("duration"):
        params["duration"] = song["duration"]
    req = urllib.request.Request(f"{server.rstrip('/')}/api/get?{urllib.parse.urlencode(params)}",
                                 headers={"Lrclib-Client": CLIENT, "User-Agent": CLIENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Unavailable(f"LRCLIB answered {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise Unavailable(f"LRCLIB couldn't be reached: {e}")
    text = (data.get("syncedLyrics") or "").strip()
    return text + "\n" if text and not data.get("instrumental") else None
