"""The connected Y1: what's on it, its sync settings and the sync itself, its player settings, Wi-Fi sync, and
backups."""
import os

from .. import backup, device, sync, wifi
from ..state import S, load_prefs
from . import USB_MOVES, get, post

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


@get("/api/device")
def info(r):
    d = S.device_info(force=r.qs.get("refresh") == "1")
    if d.get("connected"):
        d["settings"] = sync.load_settings(d["serial"])
    return d


@get("/api/device/contents", connected=True)
def contents(r):
    """Everything on the Y1 as library rows: songs InniSync synced carry the library's details (and play here);
    anything else is described from the Y1's own index."""
    c = device.contents()
    by_path = {v["path"]: k for k, v in device.manifest_for_labels().get("songs", {}).items()}
    lib = S.lib or {}
    songs, ids = [], {}

    def add(path, meta):
        if path in ids:
            return ids[path]
        jid = by_path.get(path)
        js = lib.get(jid) if jid else None
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if js:
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
    return {"songs": songs, "playlists": playlists, "indexed": c["indexed"]}


@post("/api/device/rename", connected=True)
def rename(r):
    device.set_name(r.body.get("name", "").strip() or "My Y1")
    S.device_info(force=True)
    return {"ok": True}


@post("/api/device/fixclock", connected=True)
def fix_clock(r):
    device.fix_clock()
    return {"ok": True}


@post("/api/device/rescan", connected=True)
def rescan(r):
    device.rescan_library()
    return {"ok": True}


# ---- syncing ----
@post("/api/device/settings", connected=True)
def save_settings(r):
    return sync.save_settings(r.info["serial"], r.body)


@post("/api/device/plan", connected=True)
def plan(r):
    p = sync.plan(S.library(), {**sync.DEFAULT_SETTINGS, **r.body}, S.playlist_items, S.playlists, r.info,
                  device.read_manifest())
    return ({k: v for k, v in p.items() if k not in ("want", "adds", "removes", "replaces", "playlists")} |
            {"add_count": len(p["adds"]), "remove_count": len(p["removes"]), "playlist_count": len(p["playlists"])})


@post("/api/device/sync", connected=True, exclusive=True)
def start_sync(r):
    lib = S.library()
    body = dict(r.body)
    allow_removals = bool(body.pop("allow_removals", False))   # the user confirmed a big removal
    settings = sync.save_settings(r.info["serial"], body) if body else sync.load_settings(r.info["serial"])
    settings = {**settings, "lrclib_url": load_prefs()["lrclib_url"]}
    S.job = sync.SyncJob(S.jf, lib, settings, S.playlist_items, S.playlists, soundalike=S.playlists_for_device,
                         autoplay=S.autoplay_for_device, allow_removals=allow_removals).start()
    return {"ok": True}


@get("/api/sync/status")
def sync_status(r):
    return S.job.status if S.job else {"state": "idle"}


@post("/api/sync/cancel")
def cancel_sync(r):
    if S.job:
        S.job.cancel = True
    return {"ok": True}


@post("/api/device/manifest/rebuild", connected=True, exclusive=True)
def rebuild_record(r):
    man, leftover = sync.rebuild_manifest(S.library())
    device.write_manifest(man)
    return {"songs": len(man["songs"]), "playlists": len(man["playlists"]), "unmatched": leftover}


@post("/api/device/wifi", connected=True, exclusive=True)
def wifi_sync(r):
    out = wifi.enable(r.info["serial"]) if r.body.get("on") else (wifi.disable(r.info["serial"]) or {})
    S.device_info(force=True)
    return {"ok": True, **out}


# ---- the player's own settings ----
@get("/api/device/player", connected=True)
def player(r):
    p = device.player_prefs()
    bg = p.get("bg_path")
    return {"settings": {k: p.get(k, d) for k, (d, _) in PLAYER_SETTINGS.items()},
            "wallpaper": bg if bg and bg != "THEME_DEFAULT" else None, "themeWallpaper": bg == "THEME_DEFAULT"}


@post("/api/device/player", connected=True)
def set_player(r):
    changes = {}
    for k, v in (r.body.get("settings") or {}).items():
        if k not in PLAYER_SETTINGS:
            continue
        default, allowed = PLAYER_SETTINGS[k]
        v = bool(v) if isinstance(default, bool) else int(v)
        if allowed is not None and v not in allowed:
            return {"error": f"Bad value for {k}"}, 400
        changes[k] = v
    if "eq_preset" in changes:  # InniClassic keeps the active EQ as a profile id too
        changes["eq_profile_id"] = f"preset_{changes['eq_preset']}"
    if r.body.get("wallpaper") == "theme":
        changes["bg_path"] = "THEME_DEFAULT"
    elif r.body.get("wallpaper") == "none":
        changes["bg_path"] = None
    if changes:
        device.set_player_prefs(changes)
    return {"ok": True}


# ---- backups ----
@get("/api/device/backups")
def backups(r):
    return {"backups": backup.list_backups(S.serial()), "folder": backup.chosen_root(), "auto": S.auto}


@post("/api/device/backup", connected=True, usb=USB_MOVES, exclusive=True)
def back_up(r):
    return backup.create(r.info)


@post("/api/device/restore", connected=True, usb=USB_MOVES, exclusive=True)
def restore(r):
    safety = backup.restore(r.body.get("path"), r.info, settings=bool(r.body.get("settings")),
                            playlists=bool(r.body.get("playlists")))
    backup.prune(r.info["serial"])
    return {"ok": True, "safety": safety["name"]}
