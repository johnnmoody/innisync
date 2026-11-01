"""InniSync local server: serves the UI and a small JSON API. Binds to 127.0.0.1 only."""
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import backup, device, podcasts, smart, soundalike, sync, update, wifi
from . import jellyfin
from .jellyfin import Jellyfin, NotSignedIn
from . import subsonic
from .subsonic import Subsonic

WEB = os.path.join(os.path.dirname(__file__), "web")
PREFS = os.path.join(sync.APP_DIR, "prefs.json")
LIB_CACHE = os.path.join(sync.APP_DIR, "library_cache.json")
DEFAULT_PREFS = {"backend": "jellyfin", "auto_sync": False, "auto_backup": True, "show_menubar": True, "lrclib_url": "https://lrclib.net", "lidarr_url": "", "backup_folder": "", "show_browser": False, "y1_color": "black", "accent": "y1"}
# things that move files: over this Y1's Wi-Fi they'd stall (see wifi.py), so they need the cable
USB_ONLY = {"/api/update/install", "/api/device/backup", "/api/device/restore", "/api/themes/install"}
CATALOG_REPO = "y1-community/InnioasisY1Themes"   # community themes for the Y1's original firmware
CATALOG_CACHE = os.path.join(sync.APP_DIR, "theme_catalog.json")

# InniClassic settings InniSync can change: key -> (default, allowed values). Keys/defaults read from InniClassic 1.4.5.
PLAYER_SETTINGS = {
    "shuffle": (False, None),
    "repeat_mode": (0, [0, 1, 2]),                 # off, repeat one, repeat all
    "eq_preset": (0, list(range(10))),
    "sound_check_enabled": (False, None),
    "backlight_timer_index": (3, list(range(6))),  # 10 s, 20 s, 30 s, 1 min, 2 min, always on
    "sound": (True, None),                          # click sound
    "vibrate": (True, None),
    "is_24h_format": (False, None),
    "time_in_title_bar": (False, None),
    "autoplay": (False, None),                      # InniClassic Autoplay (InniSync's build) only
}


def theme_catalog():
    """The community theme index (themes.json), cached for a day."""
    try:
        if time.time() - os.path.getmtime(CATALOG_CACHE) < 86400:
            return json.load(open(CATALOG_CACHE))
    except (OSError, ValueError):
        pass
    url = f"https://raw.githubusercontent.com/{CATALOG_REPO}/main/themes.json"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "InniSync"}), timeout=30) as r:
        data = json.load(r)
    themes = [{"name": t.get("name") or t["folder"], "folder": t["folder"], "author": t.get("author") or "",
               "description": t.get("description") or "", "screenshot": (t.get("screenshot") or "").removeprefix("./")}
              for t in data.get("themes", []) if t.get("folder")]
    os.makedirs(sync.APP_DIR, exist_ok=True)
    json.dump(themes, open(CATALOG_CACHE, "w"))
    return themes


def install_catalog_theme(folder):
    """Download one community theme folder from GitHub and copy it to the Y1's Themes folder."""
    import tempfile
    if not folder or "/" in folder or folder.startswith("."):
        raise ValueError("Not a theme folder")
    api = (f"https://api.github.com/repos/{CATALOG_REPO}/git/trees/"
           + urllib.parse.quote(f"main:{folder}", safe="") + "?recursive=1")
    with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": "InniSync", "Accept": "application/vnd.github+json"}), timeout=30) as r:
        tree = json.load(r)
    blobs = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
    if not any(b.lower() == "config.json" for b in blobs):
        raise ValueError("That theme has no config.json")
    with tempfile.TemporaryDirectory(prefix="innisync-theme-") as work:
        root = os.path.join(work, folder)
        def get(b):
            dest = os.path.join(root, *b.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            url = f"https://raw.githubusercontent.com/{CATALOG_REPO}/main/" + urllib.parse.quote(f"{folder}/{b}")
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "InniSync"}), timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(get, blobs))
        device.push_folder(root, f"{device.STOCK_THEMES}/{folder}")
    return len(blobs)


def install_theme_zip(data):
    """A zipped InniClassic theme from this computer -> Y1_Themes/<name>. The zip may hold the files or one folder of them."""
    import io
    import tempfile
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a zip file")
    names = [n for n in z.namelist() if not n.startswith("__MACOSX/") and not n.endswith("/")]
    cfg = sorted((n for n in names if n.rsplit("/", 1)[-1] == "config.json"), key=lambda n: n.count("/"))
    if not cfg:
        raise ValueError("No config.json in that zip, so it isn't an InniClassic theme")
    prefix = cfg[0][: -len("config.json")]
    meta = json.loads(z.read(cfg[0]).decode("utf-8-sig"))
    if "theme_info" in meta or "itemConfig" in meta:
        raise ValueError("That's a theme for the Y1's original player, not InniClassic")
    folder = sync.fat_safe(meta.get("name") or prefix.strip("/").rsplit("/", 1)[-1] or "Theme", 60)
    with tempfile.TemporaryDirectory(prefix="innisync-theme-") as work:
        root = os.path.join(work, folder)
        for n in names:
            if not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            dest = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "wb").write(z.read(n))
        device.push_folder(root, f"{device.INNI_THEMES}/{folder}")
    return meta.get("name") or folder


def make_wallpaper(data):
    """Any image -> 480x360 JPEG (the Y1's screen), cropped to fill. Uses macOS sips."""
    import subprocess
    import tempfile
    work = tempfile.mkdtemp(prefix="innisync-wp-")
    src, out = os.path.join(work, "src"), os.path.join(work, "wallpaper.jpg")
    open(src, "wb").write(data)
    dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", src], capture_output=True, text=True).stdout
    try:
        w = int(dims.split("pixelWidth:")[1].split()[0])
        h = int(dims.split("pixelHeight:")[1].split()[0])
    except (IndexError, ValueError):
        raise ValueError("That file isn't an image InniSync can read")
    scale = max(480 / w, 360 / h)
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90", "-z", str(round(h * scale)), str(round(w * scale)),
                    src, "--out", out], check=True, capture_output=True)
    subprocess.run(["sips", "-c", "360", "480", out], check=True, capture_output=True)
    return work, out


def load_prefs():
    try:
        return {**DEFAULT_PREFS, **json.load(open(PREFS))}
    except (OSError, ValueError):
        return dict(DEFAULT_PREFS)


def save_prefs(p):
    os.makedirs(sync.APP_DIR, exist_ok=True)
    clean = {k: p.get(k, v) for k, v in DEFAULT_PREFS.items()}
    json.dump(clean, open(PREFS, "w"), indent=1)
    backup.set_folder(clean["backup_folder"])
    return clean


class State:
    def __init__(self):
        self._jf = None
        self.qc = None          # pending Quick Connect: {"server", "secret", "code"}
        self.lock = threading.Lock()
        self.lib = None
        self.playlists = []
        self.playlist_items = {}
        self.loaded_at = 0
        self.job = None
        self.update = None       # InniClassic UpdateJob
        self.dev_cache = (0, None)

    @property
    def jf(self):
        if self._jf is None:
            self._jf = Subsonic() if load_prefs()["backend"] == "subsonic" else Jellyfin()   # raises NotSignedIn
        return self._jf

    def reset(self):
        with self.lock:
            self._jf, self.lib, self.playlists, self.playlist_items = None, None, [], {}

    def _fetch(self):
        """Full library from Jellyfin (playlists fetched in parallel), saved to the on-disk cache."""
        from concurrent.futures import ThreadPoolExecutor
        jf = self.jf
        with ThreadPoolExecutor(6) as pool:
            songs_f = pool.submit(jf.songs)
            playlists = jf.playlists()
            items = dict(zip([p["id"] for p in playlists], pool.map(lambda p: jf.playlist_items(p["id"]), playlists)))
            songs = songs_f.result()
        data = {"user": jf.user_id, "songs": songs, "playlists": playlists, "playlistItems": items, "at": time.time()}
        os.makedirs(sync.APP_DIR, exist_ok=True)
        tmp = LIB_CACHE + ".tmp"
        json.dump(data, open(tmp, "w"))
        os.replace(tmp, LIB_CACHE)
        return data

    def _apply(self, data):
        self.lib = {s["id"]: s for s in data["songs"]}
        self.jf.learn(data["songs"])
        self.jf_playlists, self.jf_items, self.loaded_at = data["playlists"], data["playlistItems"], data["at"]
        self.apply_smart()

    def apply_smart(self):
        """Jellyfin playlists plus the smart ones, worked out against the current library."""
        lists, items = smart.playlists(self.lib)
        self.playlists, self.playlist_items = self.jf_playlists + lists, {**self.jf_items, **items}

    def library(self, force=False):
        """Instant start from the disk cache (refreshed in the background), like iTunes' library file."""
        with self.lock:
            if force:
                self._apply(self._fetch())
            elif self.lib is None:
                cached = None
                try:
                    cached = json.load(open(LIB_CACHE))
                except (OSError, ValueError):
                    pass
                if cached and cached.get("user") == self.jf.user_id:
                    self._apply(cached)
                    threading.Thread(target=self._background_refresh, daemon=True).start()
                else:
                    self._apply(self._fetch())
            return self.lib

    def _background_refresh(self):
        try:
            data = self._fetch()
            with self.lock:
                self._apply(data)
        except Exception:
            pass  # keep the cached copy; next launch tries again

    def device_info(self, force=False):
        t, info = self.dev_cache
        if force or info is None or time.time() - t > 10:
            info = device.info()
            serial = info.get("serial") if info.get("connected") else None
            if serial:
                info["wifi_sync"] = wifi.enabled(serial)
            else:
                wifi.reconnect()   # Y1s with Wi-Fi sync on come back on their own
            with self.dev_lock:   # the UI and the menu bar both poll: only one of them may see the Y1 arrive
                self.dev_cache = (time.time(), info)
                arrived = serial and serial != self.connected_serial
                self.connected_serial = serial
                if serial:
                    self.last_serial = serial
            if arrived:
                threading.Thread(target=self._on_connect, args=(info,), daemon=True).start()
        return info

    def _on_connect(self, info):
        try:
            wifi.refresh(info["serial"])
        except Exception:
            pass   # the firewall refresh is retried on the next connection
        if load_prefs().get("auto_backup") and info.get("transport") == "usb":   # Wi-Fi is too slow for it
            self._auto_backup(info)

    def _auto_backup(self, info):
        if self.busy():   # a sync started first (auto-sync on connect): back up next time
            return
        self.auto = {"state": "running"}
        try:
            b = backup.auto_backup(info)
            self.auto = {"state": "done", "name": b and b["name"]}
        except Exception as e:
            self.auto = {"state": "error", "message": str(e)}

    connected_serial = None
    dev_lock = threading.Lock()
    auto = {"state": "idle"}    # the backup made when the Y1 connects

    # ---- similar songs and mixes ----
    last_serial = None
    _soundalike = (None, None)

    def busy(self):
        """Why the Y1 can't take another long job right now, or None."""
        if self.job and self.job.status["state"] in ("starting", "checking", "syncing"):
            return "A sync is already running"
        if self.update and self.update.status["state"] in update.UpdateJob.ACTIVE:
            return "The Y1 is being updated"
        if self.auto.get("state") == "running":
            return "The Y1 is being backed up. Try again in a minute."
        return None

    def serial(self):
        """The Y1's serial, or the last one seen (similar songs work while the Y1 is out with you)."""
        if self.last_serial:
            return self.last_serial
        import glob
        files = sorted(glob.glob(os.path.join(sync.APP_DIR, "device_*.json")), key=os.path.getmtime)
        return os.path.basename(files[-1])[7:-5] if files else None

    def soundalike_ids(self):
        """Songs to match by sound: everything the sync settings put on the Y1."""
        serial = self.serial()
        if not serial or not self.lib:
            return []
        return sync.selected_songs(self.lib, sync.load_settings(serial), self.playlist_items)

    def soundalike(self):
        """(index, mixes) over the Y1's songs, rebuilt when analysis or the selection changes. Also keeps analysis going."""
        ids = self.soundalike_ids()
        soundalike.ANALYZER.start(self.jf, self.lib, ids)
        key = (soundalike.ANALYZER.version, len(ids), hash(tuple(ids)))
        if self._soundalike[0] != key:
            idx = soundalike.ANALYZER.index(self.lib, ids)
            self._soundalike = (key, (idx, idx.mixes()))
        return self._soundalike[1]

    def autoplay_for_device(self, on_device):
        """{song id: its closest songs that are also on the Y1} for InniClassic Autoplay."""
        on = set(on_device)
        idx, _ = self.soundalike()
        return {i: [j for j in idx.similar(i, 40) if j in on][:15] for i in on_device if i in idx.pos}

    def playlists_for_device(self, on_device):
        """Sound-alike playlists for a sync: the mixes and each kept song's similar songs, using only songs on the Y1."""
        settings = sync.load_settings(self.serial())
        on = set(on_device)
        idx, mixes = self.soundalike()
        out = []
        if settings.get("sync_mixes", True):
            out += [{"name": m["name"], "kind": "mix", "items": [i for i in m["songs"] if i in on]} for m in mixes]
        for seed in settings.get("similar_seeds", []):
            if seed in self.lib:
                out.append({"name": self.lib[seed]["name"], "kind": "similar", "items": [seed] + [i for i in idx.similar(seed, 40) if i in on][:25]})
        return out


S = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "InniSync/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _static(self, path):
        full = os.path.realpath(os.path.join(WEB, path.lstrip("/") or "index.html"))
        if os.path.commonpath([full, os.path.realpath(WEB)]) != os.path.realpath(WEB) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy_stream(self, item_id, original=False):
        """Relay audio from the music server with the sign-in; forwards Range so seeking works. `original` is the
        untouched file (sound analysis); otherwise a format WebKit can play."""
        song = (S.lib or {}).get(item_id) or {}
        req = (S.jf.source_request(item_id, self.headers.get("Range")) if original
               else S.jf.stream_request(item_id, song.get("container"), self.headers.get("Range")))
        try:
            r = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            self.send_response(r.status)
            for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                if r.headers.get(h):
                    self.send_header(h, r.headers[h])
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # player seeked or stopped
        return None

    # ---- who may talk to this server ----
    # Any web page you visit can send requests to 127.0.0.1, so: the Host must be this server (stops DNS rebinding),
    # API calls must carry the X-InniSync header (a page on another site can't add it without a CORS preflight, which
    # this server never answers), and a page that sends an Origin must be InniSync's own. Covers, songs and Y1
    # pictures load through <img>/<audio>, which can't send headers; they're read-only.
    PUBLIC = ("/art/", "/stream/", "/devimg")

    def _allowed(self, path):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return False
        if path.startswith("/api/") and self.headers.get("X-InniSync") != "1":
            return False
        return True

    def _refuse(self):
        body = b'{"error": "Not allowed"}'
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if not self._allowed(u.path):
            return self._refuse()
        qs = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path == "/api/prefs":
                return self._json(load_prefs() | {"log": os.path.expanduser("~/Library/Logs/InniSync.log")})
            if u.path == "/api/auth":
                backend = load_prefs()["backend"]
                cfg = subsonic.load_config() if backend == "subsonic" else jellyfin.load_config()
                signed = False
                try:
                    signed = bool(S.jf)
                except NotSignedIn:
                    pass
                return self._json({"backend": backend, "server": cfg.get("server"),
                                   "user": cfg.get("user_name") if signed else None, "signedIn": signed,
                                   "jellyfinServer": jellyfin.load_config().get("server"),
                                   "subsonicServer": subsonic.load_config().get("server"),
                                   "subsonicUser": subsonic.load_config().get("user_name")})
            if u.path == "/api/auth/quickconnect/poll":
                if not S.qc:
                    return self._json({"state": "idle"})
                name = jellyfin.quick_connect_poll(S.qc["server"], S.qc["secret"])
                if name:
                    S.qc = None
                    save_prefs({**load_prefs(), "backend": "jellyfin"})
                    S.reset()
                    threading.Thread(target=S.library, daemon=True).start()
                    return self._json({"state": "signed_in", "user": name})
                return self._json({"state": "waiting", "code": S.qc["code"]})
            if u.path == "/api/library/version":
                return self._json({"loadedAt": S.loaded_at})
            if u.path == "/api/library":
                lib = S.library(force=qs.get("refresh") == "1")
                return self._json({"songs": list(lib.values()), "playlists": S.playlists,
                                   "playlistItems": S.playlist_items, "loadedAt": S.loaded_at})
            if u.path == "/api/device":
                info = S.device_info(force=qs.get("refresh") == "1")
                if info.get("connected"):
                    info["settings"] = sync.load_settings(info["serial"])
                return self._json(info)
            if u.path == "/api/smart":
                return self._json({"playlists": smart.load(), "fields": smart.FIELDS, "ops": smart.OPS,
                                   "orders": smart.ORDERS, "units": smart.UNITS})
            if u.path == "/api/update/check":
                info = S.device_info()
                return self._json(update.check(info.get("launcher") if info.get("connected") else None,
                                               force=qs.get("force") == "1"))
            if u.path == "/api/updaterce":
                return self._json(update.updater_status())
            if u.path == "/api/update/status":
                return self._json(S.update.status if S.update else {"state": "idle"})
            if u.path == "/api/device/backups":
                return self._json({"backups": backup.list_backups(S.serial()), "folder": backup.chosen_root(), "auto": S.auto})
            if u.path == "/api/device/podcasts":
                if not S.device_info().get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                return self._json(podcast_overview(force=qs.get("refresh") == "1"))
            if u.path == "/api/device/contents":
                if not S.device_info().get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                c = device.contents()
                man = manifest_or_empty().get("songs", {})
                by_path = {v["path"]: k for k, v in man.items()}
                lib = S.lib or {}
                songs, ids = [], {}
                def add(path, meta):
                    if path in ids:
                        return ids[path]
                    jid = by_path.get(path)
                    js = lib.get(jid) if jid else None
                    ext = os.path.splitext(path)[1].lstrip(".").lower()
                    if js:  # synced by InniSync: full Jellyfin details, and it can play on this computer
                        row = dict(js, container=ext or js["container"], onDevice=path)
                    else:
                        row = {"id": "dev:" + path, "name": meta.get("name") or os.path.splitext(os.path.basename(path))[0],
                               "artist": meta.get("artist", ""), "artists": [], "albumArtist": meta.get("albumArtist", ""),
                               "album": meta.get("album", ""), "albumId": None, "genres": [meta["genre"]] if meta.get("genre") else [],
                               "year": meta.get("year"), "track": meta.get("track"), "disc": None, "duration": 0,
                               "size": 0, "container": ext, "added": None, "onDevice": path, "deviceOnly": True}
                    songs.append(row)
                    ids[path] = row["id"]
                    return row["id"]
                for m in c["songs"]:
                    add(m["path"], m)
                playlists = [{"id": "devpl:" + p["name"], "name": p["name"], "items": [add(x, {}) for x in p["paths"]]}
                             for p in c["playlists"]]
                return self._json({"songs": songs, "playlists": playlists, "indexed": c["indexed"]})
            if u.path == "/api/similar/status":
                S.library()
                ids = S.soundalike_ids()
                soundalike.ANALYZER.start(S.jf, S.lib, ids)
                done = sum(1 for i in ids if i in soundalike.ANALYZER.feats)
                seeds = sync.load_settings(S.serial()).get("similar_seeds", []) if S.serial() else []
                return self._json(soundalike.ANALYZER.status | {"analyzed": done, "songs": len(ids), "seeds": seeds})
            if u.path == "/api/similar/mixes":
                S.library()
                idx, mixes = S.soundalike()
                return self._json({"mixes": [{"id": m["id"], "name": m["name"], "genres": m["genres"], "artists": m["artists"],
                                              "items": m["songs"]} for m in mixes], "analyzed": len(idx.ids)})
            if u.path == "/api/similar/songs":
                S.library()
                seed = qs.get("id", "")
                idx, _ = S.soundalike()
                if seed not in S.soundalike_ids():
                    return self._json({"error": "Similar songs only work with songs that sync to your Y1."}, 409)
                if not idx.ids or seed not in idx.pos:
                    return self._json({"error": "InniSync hasn't finished listening to this song yet. Try again in a few minutes."}, 409)
                keep = seed in sync.load_settings(S.serial()).get("similar_seeds", [])
                return self._json({"seed": seed, "items": [seed] + idx.similar(seed, 25), "kept": keep})
            if u.path == "/api/device/player":
                if not S.device_info().get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                p = device.player_prefs()
                bg = p.get("bg_path")
                return self._json({"settings": {k: p.get(k, d) for k, (d, _) in PLAYER_SETTINGS.items()},
                                   "wallpaper": bg if bg and bg != "THEME_DEFAULT" else None, "themeWallpaper": bg == "THEME_DEFAULT"})
            if u.path == "/api/device/themes":
                if not S.device_info().get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                return self._json(device.inni_themes() | {"stock": device.stock_themes()})
            if u.path == "/api/themes/catalog":
                return self._json({"themes": theme_catalog(), "repo": CATALOG_REPO})
            if u.path == "/api/device/audiobooks":
                if not S.device_info().get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                return self._json({"books": device.audiobooks()})
            if u.path == "/devimg":
                path = qs.get("path", "")
                if not path.startswith(device.SD + "/") or ".." in path or not path.lower().endswith(device.IMAGE_EXT):
                    return self._json({"error": "not an image on the Y1"}, 400)
                data = device.cat_bytes(path)
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "image/png")
                self.send_header("Cache-Control", "max-age=300")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            if u.path == "/api/sync/status":
                return self._json(S.job.status if S.job else {"state": "idle"})
            if u.path.startswith("/art/"):
                item = u.path.split("/")[2]
                try:   # signed out, unknown item or server down: the placeholder, never a broken image
                    req = S.jf.image_request(item, int(qs.get("size", 300)))
                    with urllib.request.urlopen(req, timeout=20) as r:
                        data = r.read()
                        ctype = r.headers.get("Content-Type", "image/jpeg")
                except Exception:
                    return self._static("/no_art.svg")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            if u.path.startswith("/stream/"):
                return self._proxy_stream(urllib.parse.unquote(u.path.split("/")[2]), qs.get("original") == "1")
            return self._static(u.path)
        except NotSignedIn as e:
            return self._json({"error": str(e), "signIn": True}, 401)
        except device.ManifestError as e:
            return self._json({"error": str(e), "code": "manifest"}, 409)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _raw(self, limit=4 << 30):
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > limit:
            raise ValueError("Nothing was uploaded" if not n else "That file is too big")
        return self.rfile.read(n)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._allowed(u.path) or u.path.startswith(self.PUBLIC):
            return self._refuse()
        qs = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path in ("/api/device/themes/upload", "/api/device/wallpaper", "/api/device/audiobooks/add"):
                if S.device_info().get("transport") == "wifi":
                    return self._json({"error": "Connect the Y1 by USB to copy files to it: its Wi-Fi is too slow."}, 409)
                return self._upload(u.path, qs)
            body = self._body()
            if u.path == "/api/auth/quickconnect/start":
                server = (body.get("server") or jellyfin.load_config().get("server") or jellyfin.DEFAULT_SERVER).strip().rstrip("/")
                if not server:
                    return self._json({"error": "Enter your Jellyfin server's address first"}, 400)
                if not server.startswith(("http://", "https://")):
                    server = "http://" + server
                info = jellyfin.server_info(server)
                code, secret = jellyfin.quick_connect_start(server)
                S.qc = {"server": server, "secret": secret, "code": code}
                return self._json({"code": code, "serverName": info.get("ServerName"), "server": server})
            if u.path == "/api/prefs":
                return self._json(save_prefs({**load_prefs(), **body}))
            if u.path == "/api/playlists":
                name = (body.get("name") or "").strip()
                if not name:
                    return self._json({"error": "Give the playlist a name"}, 400)
                S.jf.create_playlist(name, body.get("ids") or [])
                return self._json({"ok": True})
            if u.path == "/api/smart/preview":
                ids = smart.evaluate(smart.validate(body), S.library())
                return self._json({"count": len(ids), "seconds": sum(S.lib[i].get("duration") or 0 for i in ids),
                                   "bytes": sum(S.lib[i].get("size") or 0 for i in ids)})
            if u.path == "/api/smart/save":
                S.library()
                d = smart.save(body)
                with S.lock:
                    S.apply_smart()
                S.loaded_at = time.time()
                return self._json(d)
            if u.path == "/api/smart/delete":
                smart.delete(body.get("id"))
                for serial in sync.known_serials():   # drop it from each Y1's sync selection too
                    s = sync.load_settings(serial)
                    if body.get("id") in s["playlists"]:
                        s["playlists"].remove(body["id"])
                        sync.save_settings(serial, s)
                with S.lock:
                    S.apply_smart()
                S.loaded_at = time.time()
                return self._json({"ok": True})
            if u.path == "/api/updaterce/open":
                if S.busy():
                    return self._json({"error": S.busy()}, 409)
                dev = S.device_info()
                if dev.get("transport") == "wifi":   # it backs the Y1 up first, which needs the cable
                    return self._json({"error": "Connect the Y1 by USB first, so InniSync can back it up."}, 409)
                return self._json(update.open_updater(dev))
            if u.path == "/api/auth/subsonic":
                info = subsonic.sign_in(body.get("server") or "", (body.get("user") or "").strip(), body.get("password") or "")
                save_prefs({**load_prefs(), "backend": "subsonic"})
                S.qc = None
                S.reset()
                threading.Thread(target=S.library, daemon=True).start()
                return self._json(info)
            if u.path == "/api/auth/signout":
                S.qc = None
                (subsonic if load_prefs()["backend"] == "subsonic" else jellyfin).sign_out()
                S.reset()
                try:
                    os.remove(LIB_CACHE)
                except OSError:
                    pass
                return self._json({"ok": True})
            if u.path == "/api/similar/keep":
                serial = S.serial()
                if not serial:
                    return self._json({"error": "Connect your Y1 once so InniSync knows it"}, 409)
                s = sync.load_settings(serial)
                seeds = [x for x in s.get("similar_seeds", []) if x != body.get("id")]
                if body.get("keep"):
                    seeds.append(body["id"])
                s["similar_seeds"] = seeds
                return self._json(sync.save_settings(serial, s))
            info = S.device_info()
            if u.path == "/api/device/settings":
                if not info.get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                return self._json(sync.save_settings(info["serial"], body))
            if u.path == "/api/device/plan":
                if not info.get("connected"):
                    return self._json({"error": "The Y1 isn't connected"}, 409)
                lib = S.library()
                p = sync.plan(lib, {**sync.DEFAULT_SETTINGS, **body}, S.playlist_items, S.playlists, info,
                              device.read_manifest())
                return self._json({k: v for k, v in p.items() if k not in ("want", "adds", "removes", "playlists")} |
                                  {"add_count": len(p["adds"]), "remove_count": len(p["removes"]),
                                   "playlist_count": len(p["playlists"])})
            if u.path == "/api/sync/cancel":
                if S.job:
                    S.job.cancel = True
                return self._json({"ok": True})
            if not info.get("connected"):
                return self._json({"error": "The Y1 isn't connected"}, 409)
            if u.path == "/api/device/sync":
                if S.busy():
                    return self._json({"error": S.busy()}, 409)
                lib = S.library()
                allow_removals = bool(body.pop("allow_removals", False))   # the user confirmed a big removal
                settings = sync.save_settings(info["serial"], body) if body else sync.load_settings(info["serial"])
                settings = {**settings, "lrclib_url": load_prefs()["lrclib_url"]}
                S.job = sync.SyncJob(S.jf, lib, settings, S.playlist_items, S.playlists, soundalike=S.playlists_for_device,
                                     autoplay=S.autoplay_for_device, allow_removals=allow_removals).start()
                return self._json({"ok": True})
            if u.path == "/api/device/rename":
                device.set_name(body.get("name", "").strip() or "My Y1")
                S.device_info(force=True)
                return self._json({"ok": True})
            if u.path == "/api/device/fixclock":
                device.fix_clock()
                return self._json({"ok": True})
            if u.path == "/api/device/rescan":
                device.rescan_library()
                return self._json({"ok": True})
            if u.path == "/api/device/player":
                changes = {}
                for k, v in (body.get("settings") or {}).items():
                    if k not in PLAYER_SETTINGS:
                        continue
                    default, allowed = PLAYER_SETTINGS[k]
                    v = bool(v) if isinstance(default, bool) else int(v)
                    if allowed is not None and v not in allowed:
                        return self._json({"error": f"Bad value for {k}"}, 400)
                    changes[k] = v
                if "eq_preset" in changes:  # InniClassic keeps the active EQ as a profile id too
                    changes["eq_profile_id"] = f"preset_{changes['eq_preset']}"
                if body.get("wallpaper") == "theme":
                    changes["bg_path"] = "THEME_DEFAULT"
                elif body.get("wallpaper") == "none":
                    changes["bg_path"] = None
                if changes:
                    device.set_player_prefs(changes)
                return self._json({"ok": True})
            if u.path in USB_ONLY and info.get("transport") == "wifi" and not body.get("dryRun"):
                return self._json({"error": "Connect the Y1 by USB for this: its Wi-Fi is too slow to move files."}, 409)
            if u.path in ("/api/update/install", "/api/device/backup", "/api/device/restore"):
                if S.busy():
                    return self._json({"error": S.busy()}, 409)
                if S.auto["state"] == "running":
                    return self._json({"error": "The Y1 is being backed up. Try again in a few seconds."}, 409)
            if u.path == "/api/update/install":
                S.update = update.UpdateJob(info, dry_run=bool(body.get("dryRun"))).start()
                return self._json({"ok": True})
            if u.path == "/api/device/backup":
                return self._json(backup.create(info))
            if u.path == "/api/device/restore":
                safety = backup.restore(body.get("path"), info, settings=bool(body.get("settings")),
                                        playlists=bool(body.get("playlists")))
                backup.prune(info["serial"])
                return self._json({"ok": True, "safety": safety["name"]})
            if u.path == "/api/device/podcasts/subscribe":
                return self._json(podcasts.subscribe(body.get("url", "")))
            if u.path == "/api/device/podcasts/unsubscribe":
                return self._json(podcasts.unsubscribe(body.get("url", ""), bool(body.get("removeEpisodes"))))
            if u.path == "/api/device/manifest/rebuild":
                if S.busy():
                    return self._json({"error": S.busy()}, 409)
                man, leftover = sync.rebuild_manifest(S.library())
                device.write_manifest(man)
                return self._json({"songs": len(man["songs"]), "playlists": len(man["playlists"]), "unmatched": leftover})
            if u.path == "/api/device/wifi":
                if S.busy():
                    return self._json({"error": S.busy()}, 409)
                r = wifi.enable(info["serial"]) if body.get("on") else (wifi.disable(info["serial"]) or {})
                S.device_info(force=True)
                return self._json({"ok": True, **r})
            if u.path == "/api/device/themes/use":
                device.use_inni_theme(body.get("name", ""))
                return self._json({"ok": True})
            if u.path == "/api/device/themes/remove":
                root = device.INNI_THEMES if body.get("kind") == "inni" else device.STOCK_THEMES
                if body.get("kind") == "inni":
                    cur = device.inni_themes()
                    t = next((t for t in cur["themes"] if t["folder"] == body.get("folder")), None)
                    if t and t["name"] == cur["current"]:
                        return self._json({"error": "That theme is in use on the Y1. Pick another theme first."}, 409)
                device.remove_folder(root, body.get("folder", ""))
                return self._json({"ok": True})
            if u.path == "/api/themes/install":
                n = install_catalog_theme(body.get("folder", ""))
                return self._json({"ok": True, "files": n})
            if u.path == "/api/device/audiobooks/remove":
                device.remove_book(body.get("book", ""))
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except NotSignedIn as e:
            return self._json({"error": str(e), "signIn": True}, 401)
        except device.ManifestError as e:
            return self._json({"error": str(e), "code": "manifest"}, 409)
        except Exception as e:
            return self._json({"error": str(e)}, 500)


def manifest_or_empty():
    """The sync record for labels only (what InniSync put there): a damaged one just means no labels here. Sync and
    rebuild read it strictly."""
    try:
        return device.read_manifest()
    except device.ManifestError:
        return json.loads(json.dumps(device.EMPTY_MANIFEST))


def podcast_overview(force=False):
    """Subscriptions on the Y1 with each feed's episodes (feeds read in parallel) and which are on the Y1 now."""
    from concurrent.futures import ThreadPoolExecutor
    subs = podcasts.subscriptions()
    on_y1 = podcasts.downloaded()
    mine = manifest_or_empty().get("podcasts", {})

    def one(s):
        try:
            feed = podcasts.fetch(s["url"], force=force)
        except Exception as e:
            return {**s, "error": str(e), "episodes": []}
        eps = []
        for e in feed["episodes"][:100]:
            path = podcasts.episode_path(s["name"], e["title"])
            eps.append({**e, "title": e["title"].strip(), "onY1": path in on_y1, "byInniSync": path in mine})
        return {**s, "title": feed["title"], "image": feed["image"], "episodes": eps}
    with ThreadPoolExecutor(6) as pool:
        out = list(pool.map(one, subs))
    return {"podcasts": out, "rules": podcasts.RULES}


def _upload_impl(handler, path, qs):
    import shutil
    import subprocess
    import tempfile
    if not S.device_info().get("connected"):
        return handler._json({"error": "The Y1 isn't connected"}, 409)
    data = handler._raw()
    if path == "/api/device/themes/upload":
        return handler._json({"ok": True, "name": install_theme_zip(data)})
    if path == "/api/device/wallpaper":
        work, out = make_wallpaper(data)
        try:
            remote = f"{device.WALLPAPERS}/wallpaper-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
            device.mkdirs([device.WALLPAPERS])
            device.push(out, remote)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        device.set_player_prefs({"bg_path": remote})
        return handler._json({"ok": True, "path": remote})
    # audiobook chapter: Audiobooks/<book>/<file>. .m4b is repackaged as .m4a (InniClassic's book list skips .m4b).
    name, book = os.path.basename(qs.get("name", "")), sync.fat_safe(qs.get("book", ""), 80)
    base, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext == ".aax":
        return handler._json({"error": f"{name} is an Audible file with copy protection. The Y1 can't play it."}, 400)
    if ext not in (".mp3", ".m4a", ".m4b", ".flac", ".wav", ".ogg", ".aac", ".ape", ".wma", ".opus"):
        return handler._json({"error": f"{name} isn't an audio file the Y1 can play as a book."}, 400)
    with tempfile.TemporaryDirectory(prefix="innisync-book-") as work:
        src = os.path.join(work, "src" + ext)
        open(src, "wb").write(data)
        if ext == ".m4b":
            out = os.path.join(work, "out.m4a")
            subprocess.run([sync.FFMPEG, "-y", "-loglevel", "error", "-i", src, "-map", "0:a", "-map_chapters", "0", "-c", "copy", out], check=True, timeout=900)
            src, ext = out, ".m4a"
        dest_dir = f"{device.AUDIOBOOKS}/{book}"
        device.mkdirs([dest_dir])
        device.push(src, f"{dest_dir}/{sync.fat_safe(base, 120)}{ext}")
    return handler._json({"ok": True})


Handler._upload = lambda self, path, qs: _upload_impl(self, path, qs)


def serve(port=8765):
    backup.set_folder(load_prefs()["backup_folder"])
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    soundalike.SOURCE = f"http://127.0.0.1:{port}/stream/{{}}?original=1"
    def warm():
        try:
            S.library()
            S.soundalike()  # starts analysing any of the Y1's songs not analyzed yet
        except NotSignedIn:
            pass
        except Exception:
            pass  # analysis catches up on the next request
    threading.Thread(target=warm, daemon=True).start()
    return httpd
