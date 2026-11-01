"""What the local server keeps between requests: preferences, the signed-in music server and its library (cached on
disk for an instant start), the connected Y1, and the jobs running on it."""
import os
import threading
import time

from . import backup, device, files, smart, soundalike, sync, update, wifi
from .jellyfin import Jellyfin
from .subsonic import Subsonic

PREFS = os.path.join(sync.APP_DIR, "prefs.json")
LIB_CACHE = os.path.join(sync.APP_DIR, "library_cache.json")
DEFAULT_PREFS = {"backend": "jellyfin", "auto_sync": False, "auto_backup": True, "show_menubar": True, "lrclib_url": "https://lrclib.net", "lidarr_url": "", "backup_folder": "", "show_browser": False, "y1_color": "black", "accent": "y1"}


def load_prefs():
    try:
        return {**DEFAULT_PREFS, **files.read_json(PREFS)}
    except (OSError, ValueError):
        return dict(DEFAULT_PREFS)


def save_prefs(p):
    clean = {k: p.get(k, v) for k, v in DEFAULT_PREFS.items()}
    files.write_json(PREFS, clean, indent=1)
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
        files.write_json(LIB_CACHE, data)
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
                    cached = files.read_json(LIB_CACHE)
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
