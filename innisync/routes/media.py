"""Pictures and audio for the interface (covers, songs, pictures on the Y1), and what else goes on the Y1:
podcasts, themes, wallpapers and audiobooks."""
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import device, podcasts, sync, themes
from ..state import S
from . import USB_FILES, USB_MOVES, get, post


# ---- read by <img> and <audio>, which can't send headers (see server.PUBLIC) ----
@get("/art/", prefix=True)
def cover(r):
    item = r.path.split("/")[2]
    try:   # signed out, unknown item or server down: the placeholder, never a broken image
        req = S.jf.image_request(item, int(r.qs.get("size", 300)))
        with urllib.request.urlopen(req, timeout=20) as resp:
            data, ctype = resp.read(), resp.headers.get("Content-Type", "image/jpeg")
    except Exception:
        return r.handler.send_static("/no_art.svg")
    return r.handler.send_bytes(data, ctype, "max-age=86400")


@get("/stream/", prefix=True)
def stream(r):
    """Relay audio from the music server with the sign-in; forwards Range so seeking works. ?original=1 is the
    untouched file (sound analysis); otherwise a format WebKit can play."""
    item = urllib.parse.unquote(r.path.split("/")[2])
    rng = r.handler.headers.get("Range")
    song = (S.lib or {}).get(item) or {}
    req = (S.jf.source_request(item, rng) if r.qs.get("original") == "1"
           else S.jf.stream_request(item, song.get("container"), rng))
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        resp = e
    h = r.handler
    with resp:
        h.send_response(resp.status)
        for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
            if resp.headers.get(name):
                h.send_header(name, resp.headers[name])
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        try:
            while chunk := resp.read(64 * 1024):
                h.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # player seeked or stopped
    return None


@get("/devimg")
def y1_picture(r):
    path = r.qs.get("path", "")
    if not path.startswith(device.SD + "/") or ".." in path or not path.lower().endswith(device.IMAGE_EXT):
        return {"error": "not an image on the Y1"}, 400
    return r.handler.send_bytes(device.cat_bytes(path), mimetypes.guess_type(path)[0] or "image/png", "max-age=300")


# ---- podcasts ----
@get("/api/device/podcasts", connected=True)
def podcast_list(r):
    return podcasts.overview(force=r.qs.get("refresh") == "1")


@post("/api/device/podcasts/subscribe", connected=True)
def subscribe(r):
    return podcasts.subscribe(r.body.get("url", ""))


@post("/api/device/podcasts/unsubscribe", connected=True)
def unsubscribe(r):
    return podcasts.unsubscribe(r.body.get("url", ""), bool(r.body.get("removeEpisodes")))


# ---- themes and wallpapers ----
@get("/api/device/themes", connected=True)
def theme_list(r):
    return device.inni_themes() | {"stock": device.stock_themes()}


@get("/api/themes/catalog")
def catalog(r):
    return {"themes": themes.catalog(), "repo": themes.CATALOG_REPO}


@post("/api/themes/install", connected=True, usb=USB_MOVES)
def install_theme(r):
    return {"ok": True, "files": themes.install_from_catalog(r.body.get("folder", ""))}


@post("/api/device/themes/upload", connected=True, usb=USB_FILES, raw=True)
def upload_theme(r):
    return {"ok": True, "name": themes.install_zip(r.raw())}


@post("/api/device/themes/use", connected=True)
def use_theme(r):
    device.use_inni_theme(r.body.get("name", ""))
    return {"ok": True}


@post("/api/device/themes/remove", connected=True)
def remove_theme(r):
    root = device.INNI_THEMES if r.body.get("kind") == "inni" else device.STOCK_THEMES
    if r.body.get("kind") == "inni":
        cur = device.inni_themes()
        t = next((t for t in cur["themes"] if t["folder"] == r.body.get("folder")), None)
        if t and t["name"] == cur["current"]:
            return {"error": "That theme is in use on the Y1. Pick another theme first."}, 409
    device.remove_folder(root, r.body.get("folder", ""))
    return {"ok": True}


@post("/api/device/wallpaper", connected=True, usb=USB_FILES, raw=True)
def wallpaper(r):
    work, out = themes.make_wallpaper(r.raw())
    try:
        remote = f"{device.WALLPAPERS}/wallpaper-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        device.mkdirs([device.WALLPAPERS])
        device.push(out, remote)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    device.set_player_prefs({"bg_path": remote})
    return {"ok": True, "path": remote}


# ---- audiobooks ----
BOOK_EXT = (".mp3", ".m4a", ".m4b", ".flac", ".wav", ".ogg", ".aac", ".ape", ".wma", ".opus")


@get("/api/device/audiobooks", connected=True)
def books(r):
    return {"books": device.audiobooks()}


@post("/api/device/audiobooks/add", connected=True, usb=USB_FILES, raw=True)
def add_chapter(r):
    """One chapter: Audiobooks/<book>/<file>. .m4b is repackaged as .m4a (InniClassic's book list skips .m4b)."""
    name, book = os.path.basename(r.qs.get("name", "")), sync.fat_safe(r.qs.get("book", ""), 80)
    base, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext == ".aax":
        return {"error": f"{name} is an Audible file with copy protection. The Y1 can't play it."}, 400
    if ext not in BOOK_EXT:
        return {"error": f"{name} isn't an audio file the Y1 can play as a book."}, 400
    data = r.raw()
    with tempfile.TemporaryDirectory(prefix="innisync-book-") as work:
        src = os.path.join(work, "src" + ext)
        with open(src, "wb") as f:
            f.write(data)
        if ext == ".m4b":
            out = os.path.join(work, "out.m4a")
            subprocess.run([sync.FFMPEG, "-y", "-loglevel", "error", "-i", src, "-map", "0:a", "-map_chapters", "0",
                            "-c", "copy", out], check=True, timeout=900)
            src, ext = out, ".m4a"
        dest_dir = f"{device.AUDIOBOOKS}/{book}"
        device.mkdirs([dest_dir])
        device.push(src, f"{dest_dir}/{sync.fat_safe(base, 120)}{ext}")
    return {"ok": True}


@post("/api/device/audiobooks/remove", connected=True)
def remove_book(r):
    device.remove_book(r.body.get("book", ""))
    return {"ok": True}
