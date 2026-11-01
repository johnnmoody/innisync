"""Preferences, signing in to the music server, the library, playlists (smart ones too) and similar songs."""
import os
import sys
import threading
import time

from .. import __version__, jellyfin, smart, soundalike, subsonic, sync, system
from ..jellyfin import NotSignedIn
from ..state import LIB_CACHE, S, load_prefs, save_prefs
from . import get, post


@get("/api/prefs")
def prefs(r):
    return load_prefs() | {"log": system.log_path(), "version": __version__, "platform": sys.platform}


@post("/api/prefs")
def set_prefs(r):
    return save_prefs({**load_prefs(), **r.body})


# ---- signing in ----
@get("/api/auth")
def auth(r):
    backend = load_prefs()["backend"]
    cfg = subsonic.load_config() if backend == "subsonic" else jellyfin.load_config()
    signed = False
    try:
        signed = bool(S.jf)
    except NotSignedIn:
        pass
    return {"backend": backend, "server": cfg.get("server"),
            "user": cfg.get("user_name") if signed else None, "signedIn": signed,
            "jellyfinServer": jellyfin.load_config().get("server"),
            "subsonicServer": subsonic.load_config().get("server"),
            "subsonicUser": subsonic.load_config().get("user_name")}


@post("/api/auth/quickconnect/start")
def quickconnect_start(r):
    server = (r.body.get("server") or jellyfin.load_config().get("server") or jellyfin.DEFAULT_SERVER).strip().rstrip("/")
    if not server:
        return {"error": "Enter your Jellyfin server's address first"}, 400
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    info = jellyfin.server_info(server)
    code, secret = jellyfin.quick_connect_start(server)
    S.qc = {"server": server, "secret": secret, "code": code}
    return {"code": code, "serverName": info.get("ServerName"), "server": server}


@get("/api/auth/quickconnect/poll")
def quickconnect_poll(r):
    if not S.qc:
        return {"state": "idle"}
    name = jellyfin.quick_connect_poll(S.qc["server"], S.qc["secret"])
    if name:
        S.qc = None
        save_prefs({**load_prefs(), "backend": "jellyfin"})
        S.reset()
        threading.Thread(target=S.library, daemon=True).start()
        return {"state": "signed_in", "user": name}
    return {"state": "waiting", "code": S.qc["code"]}


@post("/api/auth/subsonic")
def subsonic_sign_in(r):
    info = subsonic.sign_in(r.body.get("server") or "", (r.body.get("user") or "").strip(), r.body.get("password") or "")
    save_prefs({**load_prefs(), "backend": "subsonic"})
    S.qc = None
    S.reset()
    threading.Thread(target=S.library, daemon=True).start()
    return info


@post("/api/auth/signout")
def sign_out(r):
    S.qc = None
    (subsonic if load_prefs()["backend"] == "subsonic" else jellyfin).sign_out()
    S.reset()
    try:
        os.remove(LIB_CACHE)
    except OSError:
        pass
    return {"ok": True}


# ---- library and playlists ----
@get("/api/library")
def library(r):
    lib = S.library(force=r.qs.get("refresh") == "1")
    return {"songs": list(lib.values()), "playlists": S.playlists, "playlistItems": S.playlist_items,
            "loadedAt": S.loaded_at}


@get("/api/library/version")
def library_version(r):
    return {"loadedAt": S.loaded_at}


@post("/api/playlists")
def new_playlist(r):
    name = (r.body.get("name") or "").strip()
    if not name:
        return {"error": "Give the playlist a name"}, 400
    S.jf.create_playlist(name, r.body.get("ids") or [])
    return {"ok": True}


@get("/api/smart")
def smart_playlists(r):
    return {"playlists": smart.load(), "fields": smart.FIELDS, "ops": smart.OPS, "orders": smart.ORDERS,
            "units": smart.UNITS}


@post("/api/smart/preview")
def smart_preview(r):
    ids = smart.evaluate(smart.validate(r.body), S.library())
    return {"count": len(ids), "seconds": sum(S.lib[i].get("duration") or 0 for i in ids),
            "bytes": sum(S.lib[i].get("size") or 0 for i in ids)}


@post("/api/smart/save")
def smart_save(r):
    S.library()
    d = smart.save(r.body)
    with S.lock:
        S.apply_smart()
    S.loaded_at = time.time()
    return d


@post("/api/smart/delete")
def smart_delete(r):
    smart.delete(r.body.get("id"))
    for serial in sync.known_serials():   # drop it from each Y1's sync selection too
        s = sync.load_settings(serial)
        if r.body.get("id") in s["playlists"]:
            s["playlists"].remove(r.body["id"])
            sync.save_settings(serial, s)
    with S.lock:
        S.apply_smart()
    S.loaded_at = time.time()
    return {"ok": True}


# ---- similar songs and mixes ----
@get("/api/similar/status")
def similar_status(r):
    S.library()
    ids = S.soundalike_ids()
    soundalike.ANALYZER.start(S.jf, S.lib, ids)
    done = sum(1 for i in ids if i in soundalike.ANALYZER.feats)
    seeds = sync.load_settings(S.serial()).get("similar_seeds", []) if S.serial() else []
    return soundalike.ANALYZER.status | {"analyzed": done, "songs": len(ids), "seeds": seeds}


@get("/api/similar/mixes")
def mixes(r):
    S.library()
    idx, found = S.soundalike()
    return {"mixes": [{"id": m["id"], "name": m["name"], "genres": m["genres"], "artists": m["artists"],
                       "items": m["songs"]} for m in found], "analyzed": len(idx.ids)}


@get("/api/similar/songs")
def similar_songs(r):
    S.library()
    seed = r.qs.get("id", "")
    idx, _ = S.soundalike()
    if seed not in S.soundalike_ids():
        return {"error": "Similar songs only work with songs that sync to your Y1."}, 409
    if not idx.ids or seed not in idx.pos:
        return {"error": "InniSync hasn't finished listening to this song yet. Try again in a few minutes."}, 409
    keep = seed in sync.load_settings(S.serial()).get("similar_seeds", [])
    return {"seed": seed, "items": [seed] + idx.similar(seed, 25), "kept": keep}


@post("/api/similar/keep")
def keep_similar(r):
    serial = S.serial()
    if not serial:
        return {"error": "Connect your Y1 once so InniSync knows it"}, 409
    s = sync.load_settings(serial)
    seeds = [x for x in s.get("similar_seeds", []) if x != r.body.get("id")]
    if r.body.get("keep"):
        seeds.append(r.body["id"])
    s["similar_seeds"] = seeds
    return sync.save_settings(serial, s)
