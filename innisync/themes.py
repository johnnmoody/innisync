"""Themes and wallpapers for the Y1: the community catalog for its original player, zipped InniClassic themes from
this computer, and pictures turned into wallpapers."""
import json
import os
import time
import urllib.parse
import urllib.request

from . import device, files, sync, system

CATALOG_REPO = "y1-community/InnioasisY1Themes"   # community themes for the Y1's original firmware
CATALOG_CACHE = os.path.join(sync.APP_DIR, "theme_catalog.json")


def catalog():
    """The community theme index (themes.json), cached for a day."""
    try:
        if time.time() - os.path.getmtime(CATALOG_CACHE) < 86400:
            return files.read_json(CATALOG_CACHE)
    except (OSError, ValueError):
        pass
    url = f"https://raw.githubusercontent.com/{CATALOG_REPO}/main/themes.json"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "InniSync"}), timeout=30) as r:
        data = json.load(r)
    themes = [{"name": t.get("name") or t["folder"], "folder": t["folder"], "author": t.get("author") or "",
               "description": t.get("description") or "", "screenshot": (t.get("screenshot") or "").removeprefix("./")}
              for t in data.get("themes", []) if t.get("folder")]
    files.write_json(CATALOG_CACHE, themes)
    return themes


def install_from_catalog(folder):
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


def install_zip(data):
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
            with open(dest, "wb") as f:
                f.write(z.read(n))
        device.push_folder(root, f"{device.INNI_THEMES}/{folder}")
    return meta.get("name") or folder


def make_wallpaper(data):
    """Any image -> 480x360 JPEG (the Y1's screen), cropped to fill. Returns (work folder, jpeg path)."""
    import io
    import tempfile
    from PIL import Image, ImageOps, UnidentifiedImageError
    work = tempfile.mkdtemp(prefix="innisync-wp-")
    out = os.path.join(work, "wallpaper.jpg")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        if not system.MAC:
            raise ValueError("That file isn't an image InniSync can read")
        img = Image.open(io.BytesIO(_sips_to_jpeg(data, work)))   # HEIC photos and the like: macOS can read them
    img = ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (480, 360), Image.Resampling.LANCZOS)
    img.save(out, "JPEG", quality=90)
    return work, out


def _sips_to_jpeg(data, work):
    import subprocess
    src, jpg = os.path.join(work, "src"), os.path.join(work, "src.jpg")
    with open(src, "wb") as f:
        f.write(data)
    if subprocess.run(["sips", "-s", "format", "jpeg", src, "--out", jpg], capture_output=True).returncode != 0:
        raise ValueError("That file isn't an image InniSync can read")
    with open(jpg, "rb") as f:
        return f.read()
