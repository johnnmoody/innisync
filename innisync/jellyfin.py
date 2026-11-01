"""Minimal Jellyfin client for InniSync (library, playlists, file download, artwork)."""
import datetime
import json
import os
import re
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import files, system

# where InniSync keeps its settings and caches; INNISYNC_DATA points a second copy (development, demos) elsewhere
APP_DIR = system.data_dir()
CONFIG = os.path.join(APP_DIR, "jellyfin.json")      # server URL + signed-in user (no secrets)
KEYCHAIN_SERVICE = "InniSync Jellyfin"                  # access token, kept in the system's secret store (system.py)
CLIENT = {"Client": "InniSync", "Device": socket.gethostname().split(".")[0] or "Mac",
          "DeviceId": "innisync-" + (socket.gethostname().split(".")[0] or "mac").lower(), "Version": "1.0"}
DEFAULT_SERVER = ""   # asked for in Preferences

SONG_FIELDS = "Path,MediaSources,Genres,DateCreated,ParentId"


class NotSignedIn(Exception):
    pass


def load_config():
    try:
        return files.read_json(CONFIG)
    except (OSError, ValueError):
        return {"server": DEFAULT_SERVER}


def save_config(cfg):
    files.write_json(CONFIG, cfg, indent=1)


def auth_header(token=None):
    parts = [f'{k}="{v}"' for k, v in CLIENT.items()]
    if token:
        parts.append(f'Token="{token}"')
    return "MediaBrowser " + ", ".join(parts)


def _raw(method, server, path, body=None, token=None, timeout=30):
    req = urllib.request.Request(server.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": auth_header(token), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        return json.loads(data) if data else None


def server_info(server):
    return _raw("GET", server, "/System/Info/Public", timeout=8)


def quick_connect_start(server):
    """Returns (code to show the user, secret kept by InniSync)."""
    if not _raw("GET", server, "/QuickConnect/Enabled", timeout=8):
        raise RuntimeError("Quick Connect is turned off on this Jellyfin server (Dashboard > General)")
    r = _raw("POST", server, "/QuickConnect/Initiate")
    return r["Code"], r["Secret"]


def quick_connect_poll(server, secret):
    """None while waiting; on approval, signs in, stores the token in the system's secret store and returns the user name."""
    st = _raw("GET", server, "/QuickConnect/Connect?" + urllib.parse.urlencode({"secret": secret}))
    if not st.get("Authenticated"):
        return None
    auth = _raw("POST", server, "/Users/AuthenticateWithQuickConnect", {"Secret": secret})
    user = auth["User"]
    system.secret_set(KEYCHAIN_SERVICE, server, auth["AccessToken"])
    save_config({"server": server, "user_id": user["Id"], "user_name": user["Name"]})
    return user["Name"]


def sign_out():
    cfg = load_config()
    token = system.secret_get(KEYCHAIN_SERVICE, cfg.get("server", ""))
    if token:
        try:
            _raw("POST", cfg["server"], "/Sessions/Logout", token=token, timeout=8)
        except Exception:
            pass
    system.secret_delete(KEYCHAIN_SERVICE, cfg.get("server", ""))
    save_config({"server": cfg.get("server", DEFAULT_SERVER)})


def norm(s):
    s = (s or "").replace("’", "").replace("'", "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s*[\(\[][^\)\]]*(feat|with|remaster|version|edit|explicit|deluxe|live|mono|stereo)[^\)\]]*[\)\]]", "", s)
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class Jellyfin:
    """Signed-in Jellyfin user (Quick Connect token from the system's secret store)."""

    def __init__(self):
        cfg = load_config()
        self.base = cfg.get("server", DEFAULT_SERVER).rstrip("/")
        self.user_id = cfg.get("user_id")
        self.user_name = cfg.get("user_name")
        self.key = system.secret_get(KEYCHAIN_SERVICE, cfg.get("server", "")) if self.user_id else None
        if not self.key:
            raise NotSignedIn("Sign in to Jellyfin in InniSync Preferences")

    def headers(self):
        return {"Authorization": auth_header(self.key), "Content-Type": "application/json"}

    def call(self, method, path, body=None, timeout=60):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers=self.headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return json.loads(data) if data else None

    def items(self, **params):
        params.setdefault("userId", self.user_id)
        params.setdefault("Recursive", "true")
        return self.call("GET", "/Items?" + urllib.parse.urlencode(params), timeout=180)

    # ---- library -----------------------------------------------------------
    def songs(self):
        """All audio items as compact dicts."""
        res = self.items(IncludeItemTypes="Audio", Fields=SONG_FIELDS, SortBy="AlbumArtist,Album,ParentIndexNumber,IndexNumber")
        out = []
        for it in res["Items"]:
            ms = (it.get("MediaSources") or [{}])[0]
            out.append({
                "id": it["Id"],
                "name": it.get("Name", ""),
                "artist": (it.get("Artists") or [it.get("AlbumArtist") or ""])[0],
                "artists": it.get("Artists") or [],
                "albumArtist": it.get("AlbumArtist") or "",
                "album": it.get("Album") or "",
                "albumId": it.get("AlbumId"),
                "genres": it.get("Genres") or [],
                "year": it.get("ProductionYear"),
                "track": it.get("IndexNumber"),
                "disc": it.get("ParentIndexNumber"),
                "duration": round((it.get("RunTimeTicks") or 0) / 10_000_000),
                "size": ms.get("Size") or 0,
                "container": (ms.get("Container") or os.path.splitext(it.get("Path") or "")[1].lstrip(".")).lower(),
                "bitrate": ms.get("Bitrate"),
                "added": it.get("DateCreated"),
                "lyrics": bool(it.get("HasLyrics")),
                "plays": (it.get("UserData") or {}).get("PlayCount") or 0,
                "lastPlayed": (it.get("UserData") or {}).get("LastPlayedDate"),
                "favorite": bool((it.get("UserData") or {}).get("IsFavorite")),
            })
        return out

    def lrc(self, item_id):
        """Timed lyrics as .lrc text, or None. Untimed lyrics are skipped: InniClassic ignores an .lrc without
        timestamps (and then won't fall back to lyrics embedded in the song)."""
        try:
            data = self.call("GET", f"/Audio/{item_id}/Lyrics", timeout=30) or {}
        except urllib.error.HTTPError:
            return None
        lines = [l for l in data.get("Lyrics") or [] if l.get("Start") is not None]
        if not lines:
            return None
        def ts(ticks):
            cs = int(ticks) // 100_000          # 100 ns ticks -> hundredths of a second
            return f"[{cs // 6000:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}]"
        return "\n".join(ts(l["Start"]) + (l.get("Text") or "") for l in lines) + "\n"

    def last_played(self, item_id):
        """When this user last played the song (UTC), or None."""
        s = (self.call("GET", f"/UserItems/{item_id}/UserData?userId={self.user_id}") or {}).get("LastPlayedDate")
        # Jellyfin writes 7 fraction digits, which fromisoformat rejects
        return datetime.datetime.fromisoformat(s[:19]).replace(tzinfo=datetime.timezone.utc) if s else None

    def mark_played(self, item_id, when):
        """Count one play. With a date, Jellyfin adds 1 to PlayCount and sets LastPlayedDate to that date."""
        q = urllib.parse.urlencode({"userId": self.user_id, "datePlayed": when.strftime("%Y-%m-%dT%H:%M:%S.000Z")})
        return self.call("POST", f"/UserPlayedItems/{item_id}?{q}")

    def playlists(self):
        res = self.items(IncludeItemTypes="Playlist", Fields="ChildCount")
        return [{"id": p["Id"], "name": p["Name"], "count": p.get("ChildCount", 0)} for p in res["Items"]]

    def playlist_items(self, playlist_id):
        res = self.call("GET", f"/Playlists/{playlist_id}/Items?userId={self.user_id}&Fields=MediaSources", timeout=120)
        return [it["Id"] for it in res["Items"]]

    def create_playlist(self, name, ids):
        return self.call("POST", "/Playlists", {"Name": name, "Ids": ids, "UserId": self.user_id, "MediaType": "Audio"})

    # ---- media -------------------------------------------------------------
    def learn(self, songs):
        """Nothing to pick up from cached songs: Jellyfin serves art by item id."""

    def open_download(self, item_id):
        req = urllib.request.Request(f"{self.base}/Items/{item_id}/Download", headers=self.headers())
        return urllib.request.urlopen(req, timeout=300)

    def image_request(self, item_id, size=300):
        return urllib.request.Request(f"{self.base}/Items/{item_id}/Images/Primary?maxWidth={size}&quality=90",
                                      headers=self.headers())

    WEBKIT_NATIVE = {"mp3", "flac", "m4a", "aac", "alac", "wav"}

    def stream_request(self, item_id, container=None, range_header=None):
        """Request for playing a song in WebKit (auth in the header, see the server's /stream proxy).
        Formats WebKit plays natively are streamed untouched (fast start); anything else is converted to MP3."""
        if container in self.WEBKIT_NATIVE:
            url = f"{self.base}/Audio/{item_id}/stream?static=true"
        else:
            q = urllib.parse.urlencode({"UserId": self.user_id, "Container": "mp3,flac,aac,m4a,wav",
                                        "AudioCodec": "mp3", "TranscodingContainer": "mp3"})
            url = f"{self.base}/Audio/{item_id}/universal?{q}"
        hdrs = self.headers()
        if range_header:
            hdrs["Range"] = range_header
        return urllib.request.Request(url, headers=hdrs)

    def source_request(self, item_id, range_header=None):
        """Request for the original audio file (sound analysis reads it through the server's /stream proxy, so the
        sign-in never goes on an ffmpeg command line where other programs could read it)."""
        hdrs = self.headers()
        if range_header:
            hdrs["Range"] = range_header
        return urllib.request.Request(f"{self.base}/Audio/{item_id}/stream?static=true", headers=hdrs)
