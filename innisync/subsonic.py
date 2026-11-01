"""Subsonic / OpenSubsonic client (Navidrome, gonic, Airsonic-Advanced, LMS, ...), the same shape as jellyfin.Jellyfin.

Auth is the Subsonic token scheme: each request carries u, t = md5(password + salt) and s = salt, so the password
itself never goes over the wire; it's kept in the macOS Keychain ("InniSync Subsonic"). The whole library comes from
search3 with an empty query, paged (OpenSubsonic servers allow that for exactly this, Navidrome included).
Timed lyrics use OpenSubsonic getLyricsBySongId when the server lists the songLyrics extension.
"""
import datetime
import hashlib
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from .jellyfin import APP_DIR, NotSignedIn

CONFIG = os.path.join(APP_DIR, "subsonic.json")   # server URL + user name (no secrets)
KEYCHAIN_SERVICE = "InniSync Subsonic"
API = "1.16.1"
PAGE = 500
UA = {"User-Agent": "InniSync"}   # some servers (the Navidrome demo, behind a filter) refuse Python's default


class SubsonicError(Exception):
    pass


def load_config():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG, "w"), indent=1)


def _keychain(action, account, secret=None):
    if action == "get":
        p = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    if action == "set":
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", secret],
                       capture_output=True, check=True)
    if action == "delete":
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account], capture_output=True)


def _account(server, user):
    return f"{user}@{server}"


def _query(user, password, **params):
    salt = secrets.token_hex(8)
    q = [("u", user), ("t", hashlib.md5((password + salt).encode()).hexdigest()), ("s", salt),
         ("v", API), ("c", "InniSync"), ("f", "json")]
    for k, v in params.items():
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            q.append((k, item))
    return urllib.parse.urlencode(q)


def _call(server, user, password, method, timeout=60, **params):
    url = f"{server.rstrip('/')}/rest/{method}?{_query(user, password, **params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        res = json.load(r)["subsonic-response"]
    if res.get("status") != "ok":
        err = res.get("error") or {}
        if err.get("code") in (40, 41, 44):   # wrong credentials / token auth not supported for this user
            raise NotSignedIn(err.get("message") or "Wrong user name or password")
        raise SubsonicError(err.get("message") or f"{method} failed")
    return res


def sign_in(server, user, password):
    """Check the credentials against the server, then keep them (password in the Keychain). Returns server info."""
    server = server.strip().rstrip("/")
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    res = _call(server, user, password, "ping", timeout=10)
    _keychain("set", _account(server, user), password)
    save_config({"server": server, "user_name": user})
    return {"server": server, "user": user, "type": res.get("type") or "subsonic", "version": res.get("serverVersion")}


def sign_out():
    cfg = load_config()
    if cfg.get("server") and cfg.get("user_name"):
        _keychain("delete", _account(cfg["server"], cfg["user_name"]))
    save_config({"server": cfg.get("server", "")})


def _iso(s):
    return s[:19] + "Z" if s else None


class Subsonic:
    """Signed-in Subsonic user."""
    WEBKIT_NATIVE = {"mp3", "flac", "m4a", "aac", "alac", "wav"}

    def __init__(self):
        cfg = load_config()
        self.base, self.user = cfg.get("server"), cfg.get("user_name")
        self.password = _keychain("get", _account(self.base, self.user)) if self.base and self.user else None
        if not self.password:
            raise NotSignedIn("Not signed in to a Subsonic server")
        self.user_id = _account(self.base, self.user)   # keys the library cache, like Jellyfin's user id
        self.cover = {}       # song or album id -> coverArt id (getCoverArt wants the latter)
        self._ext = None

    def call(self, method, timeout=60, **params):
        return _call(self.base, self.user, self.password, method, timeout=timeout, **params)

    def url(self, method, **params):
        return f"{self.base}/rest/{method}?{_query(self.user, self.password, **params)}"

    def extensions(self):
        if self._ext is None:
            try:
                self._ext = {e["name"] for e in self.call("getOpenSubsonicExtensions").get("openSubsonicExtensions", [])}
            except Exception:
                self._ext = set()
        return self._ext

    # ---- library -----------------------------------------------------------
    def _song(self, it):
        if it.get("coverArt"):
            self.cover[it["id"]] = it["coverArt"]
            if it.get("albumId"):
                self.cover.setdefault(it["albumId"], it["coverArt"])
        genres = [g["name"] for g in it.get("genres") or [] if g.get("name")] or ([it["genre"]] if it.get("genre") else [])
        artists = [a["name"] for a in it.get("artists") or [] if a.get("name")]
        return {
            "id": it["id"], "name": it.get("title", ""),
            "artist": it.get("displayArtist") or it.get("artist") or (artists[0] if artists else ""),
            "artists": artists or ([it["artist"]] if it.get("artist") else []),
            "albumArtist": it.get("displayAlbumArtist") or "", "album": it.get("album") or "",
            "albumId": it.get("albumId"), "genres": genres, "year": it.get("year"), "track": it.get("track"),
            "disc": it.get("discNumber"), "duration": it.get("duration") or 0, "size": it.get("size") or 0,
            "container": (it.get("suffix") or os.path.splitext(it.get("path") or "")[1].lstrip(".")).lower(),
            "bitrate": (it.get("bitRate") or 0) * 1000 or None, "added": _iso(it.get("created")),
            "lyrics": "songLyrics" in self.extensions(),   # the server can say; asked per song at sync time
            "plays": it.get("playCount") or 0, "lastPlayed": _iso(it.get("played")), "favorite": bool(it.get("starred")),
            "art": it.get("coverArt"),
        }

    def learn(self, songs):
        """Cover-art ids from songs read back from the disk cache."""
        for s in songs:
            if s.get("art"):
                self.cover[s["id"]] = s["art"]
                if s.get("albumId"):
                    self.cover.setdefault(s["albumId"], s["art"])

    def songs(self):
        out, offset = [], 0
        while True:
            res = self.call("search3", timeout=180, query="", songCount=PAGE, songOffset=offset, artistCount=0, albumCount=0)
            page = (res.get("searchResult3") or {}).get("song") or []
            out += [self._song(s) for s in page]
            if len(page) < PAGE:
                return out
            offset += PAGE

    def playlists(self):
        res = self.call("getPlaylists")
        return [{"id": p["id"], "name": p["name"], "count": p.get("songCount", 0)}
                for p in (res.get("playlists") or {}).get("playlist") or []]

    def playlist_items(self, playlist_id):
        res = self.call("getPlaylist", timeout=120, id=playlist_id)
        return [e["id"] for e in (res.get("playlist") or {}).get("entry") or []]

    def create_playlist(self, name, ids):
        return self.call("createPlaylist", name=name, songId=list(ids))

    def lrc(self, item_id):
        """Timed lyrics as .lrc text, or None (OpenSubsonic songLyrics only)."""
        if "songLyrics" not in self.extensions():
            return None
        res = self.call("getLyricsBySongId", timeout=30, id=item_id)
        for lyr in (res.get("lyricsList") or {}).get("structuredLyrics") or []:
            if lyr.get("synced") and lyr.get("line"):
                def ts(ms):
                    ms = int(ms or 0)
                    return f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]"
                return "\n".join(f"{ts(l.get('start'))}{l.get('value', '')}" for l in lyr["line"]) + "\n"
        return None

    # ---- play counts -------------------------------------------------------
    def last_played(self, item_id):
        s = (self.call("getSong", id=item_id).get("song") or {}).get("played")
        return datetime.datetime.fromisoformat(s[:19]).replace(tzinfo=datetime.timezone.utc) if s else None

    def mark_played(self, item_id, when):
        """Count one play at that time (scrobble with submission=true adds to playCount and sets the play date)."""
        return self.call("scrobble", id=item_id, time=int(when.timestamp() * 1000), submission="true")

    # ---- media -------------------------------------------------------------
    def open_download(self, item_id):
        return urllib.request.urlopen(urllib.request.Request(self.url("download", id=item_id), headers=UA), timeout=300)

    def stream_request(self, item_id, container=None, range_header=None):
        """Request for playing a song in WebKit: untouched when WebKit plays the format, else MP3 from the server."""
        url = self.url("stream", id=item_id, format="raw") if container in self.WEBKIT_NATIVE else \
            self.url("stream", id=item_id, format="mp3", maxBitRate=320)
        return urllib.request.Request(url, headers={**UA, "Range": range_header} if range_header else UA)

    def image_request(self, item_id, size=300):
        return urllib.request.Request(self.url("getCoverArt", id=self.cover.get(item_id, item_id), size=size), headers=UA)

    def audio_source(self, item_id):
        """(url, extra ffmpeg headers) for reading the original audio (sound analysis)."""
        return self.url("stream", id=item_id, format="raw"), "User-Agent: InniSync\r\n"
