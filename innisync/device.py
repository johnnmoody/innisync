"""Innioasis Y1 over adb (root adbd). No USB-storage mode: Android keeps the card, files go via adb push."""
import json
import os
import re
import shlex
import subprocess
import tempfile

from . import tools

ADB = tools.find("adb", "INNISYNC_ADB")
SD = "/storage/sdcard0"
SYNC_DIR = f"{SD}/Music/InniSync"
PLAYLIST_DIR = f"{SD}/Y1_Playlists"
MANIFEST = f"{SYNC_DIR}/.innisync_manifest.json"
ORIGINAL = "com.themoon.y1"
AUTOPLAY = "com.themoon.y1.autoplay"  # InniClassic Autoplay, InniSync's build of the player
LAUNCHER = ORIGINAL                  # the InniClassic InniSync works with; set_launcher() switches it
ACTIVITY = "com.themoon.y1.MainActivity"   # the same class in both packages
LIBRARY_CACHE = f"{SD}/.y1_library_cache.json"
SCROBBLER_LOG = f"{SD}/.scrobbler.log"
PREFS_DIR = f"/data/data/{LAUNCHER}/shared_prefs"
PLAYER_PREFS = f"{PREFS_DIR}/Y1_SETTINGS.xml"
INNI_THEMES = f"{SD}/Y1_Themes"      # InniClassic's own themes (config.json + assets)
STOCK_THEMES = f"{SD}/Themes"        # the original Y1 firmware's themes (ignored by InniClassic)
AUDIOBOOKS = f"{SD}/Audiobooks"      # the only folder InniClassic treats as books (resume + bookmarks)
WALLPAPERS = f"{SD}/Pictures/InniSync"
PLAYLIST_PREFIX = "InniSync - "      # playlists InniSync writes to the Y1 (sync.py uses the same)
IMAGE_EXT = (".png", ".jpg", ".jpeg")
# InniClassic plays these natively; anything else is converted on sync.
PLAYABLE = {"mp3", "flac", "wav", "ogg", "opus", "m4a", "aac", "alac"}


class DeviceError(Exception):
    pass


class InstallError(DeviceError):
    """adb install refused the APK; .code is Android's reason, e.g. INSTALL_FAILED_UPDATE_INCOMPATIBLE."""
    def __init__(self, code, output):
        super().__init__(f"The Y1 refused the install ({code})")
        self.code, self.output = code, output


# The Y1 can be reachable over USB and Wi-Fi at once (its adbd listens on both), and adb then refuses commands
# without -s. connected() picks the transport (USB first) and every call goes to it.
_transport = None
GLOBAL_CMDS = ("devices", "connect", "disconnect", "start-server", "kill-server")


WIFI_SLOWER = 8   # this Y1's Wi-Fi is slow and laggy (see wifi.py), so small calls over it get longer to finish


def adb(*args, timeout=60, check=True):
    if over_wifi():
        timeout *= WIFI_SLOWER
    cmd = [ADB, "-s", _transport, *args] if _transport and args[0] not in GLOBAL_CMDS else [ADB, *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise DeviceError((p.stderr or p.stdout).strip() or f"adb {args[0]} failed")
    return p.stdout


def shell(cmd, timeout=60):
    return adb("shell", cmd, timeout=timeout).replace("\r", "")


def shell_ok(cmd, timeout=60):
    """shell(), but raises DeviceError when the command fails on the Y1. Android 4.2's adb doesn't pass back exit
    codes (that came with Android 7), so the status is echoed after the command and read back."""
    out = shell(f"{cmd}; echo __RC=$?", timeout=timeout)
    body, _, rc = out.rstrip("\n").rpartition("__RC=")
    if rc.strip() != "0":
        raise DeviceError(body.strip()[-300:] or f"The Y1 couldn't run: {cmd[:80]}")
    return body


def q(path):
    return shlex.quote(path)


def connected():
    """The adb transport of the connected Y1 (USB serial, or ip:port over Wi-Fi), or None."""
    global _transport
    try:
        out = adb("devices", "-l", timeout=10)
    except Exception:
        return None
    found = [l.split()[0] for l in out.splitlines()[1:] if " device " in l + " " and "model:Y1" in l]
    found.sort(key=lambda s: ":" in s)   # USB before Wi-Fi
    _transport = found[0] if found else None
    return _transport


def over_wifi():
    return bool(_transport and ":" in _transport)


def _prop(name):
    return shell(f"getprop {name}").strip()


def _pkg_version(pkg):
    out = shell(f"dumpsys package {pkg} | grep -m1 versionName")
    m = re.search(r"versionName=(\S+)", out)
    return m.group(1) if m else None


def _du_bytes(path):
    out = shell(f"du -sk {q(path)} 2>/dev/null")
    m = re.match(r"(\d+)", out.strip())
    return int(m.group(1)) * 1024 if m else 0


def info():
    transport = connected()
    if not transport:
        return {"connected": False}
    serial = _prop("ro.serialno") or transport   # the same Y1 over USB or Wi-Fi
    set_launcher(AUTOPLAY if AUTOPLAY in shell(f"pm list packages -e {AUTOPLAY}") else ORIGINAL)   # -e: enabled only
    bat = shell("dumpsys battery")
    level = re.search(r"level: (\d+)", bat)
    plugged = re.search(r"(AC|USB) powered: true", bat)
    st = shell(f"stat -f -c '%b %f %S' {SD} 2>/dev/null || df {SD}")
    total = free = 0
    m = re.match(r"(\d+) (\d+) (\d+)", st.strip())
    if m:
        blocks, bfree, bsize = map(int, m.groups())
        total, free = blocks * bsize, bfree * bsize
    else:  # toolbox df: Filesystem Size Used Free Blksize
        line = [l for l in st.splitlines() if l.startswith(SD)]
        if line:
            def g(v):
                mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
                return int(float(v[:-1]) * mult[v[-1]]) if v[-1] in mult else int(v)
            parts = line[0].split()
            total, free = g(parts[1]), g(parts[3])
    used = total - free
    audio = _du_bytes(f"{SD}/Music") + _du_bytes(f"{SD}/Podcasts") + _du_bytes(f"{SD}/Audiobooks")
    video = _du_bytes(f"{SD}/Movies") + _du_bytes(f"{SD}/Videos")
    photos = _du_bytes(f"{SD}/DCIM") + _du_bytes(f"{SD}/Pictures")
    synced = _du_bytes(SYNC_DIR)
    clock_ok = int(shell("date +%Y").strip() or 0) >= 2025
    wifi = shell("dumpsys wifi | grep -m1 mWifiInfo")
    ssid = re.search(r"SSID: ([^,]*),", wifi)
    return {
        "connected": True,
        "serial": serial,
        "transport": "wifi" if over_wifi() else "usb",
        "name": _prop("persist.innisync.name") or "My Y1",
        "model": _prop("ro.product.model"),
        "firmware": _prop("ro.custom.build.version") or _prop("ro.build.display.id"),
        "android": _prop("ro.build.version.release"),
        "launcher": _pkg_version(LAUNCHER),
        "launcher_pkg": LAUNCHER,
        "battery": int(level.group(1)) if level else None,
        "charging": bool(plugged),
        "capacity": total,
        "free": free,
        "audio": audio,
        "video": video,
        "photos": photos,
        "other": max(used - audio - video - photos, 0),
        "synced": synced,
        "clock_ok": clock_ok,
        "wifi": (ssid.group(1).strip() if ssid and "unknown" not in ssid.group(1) else "") or None,
    }


def set_launcher(pkg):
    """Work with this InniClassic: the Autoplay build whenever it's installed (it's only there to be used)."""
    global LAUNCHER, PREFS_DIR, PLAYER_PREFS
    LAUNCHER = pkg
    PREFS_DIR = f"/data/data/{pkg}/shared_prefs"
    PLAYER_PREFS = f"{PREFS_DIR}/Y1_SETTINGS.xml"


def set_name(name):
    shell(f"setprop persist.innisync.name {q(name)}")


class ManifestError(DeviceError):
    """The Y1's sync record exists but can't be read. Syncing on would treat the Y1 as empty and copy everything again
    (or lose track of what to remove), so callers stop instead."""


EMPTY_MANIFEST = {"songs": {}, "playlists": []}


def read_manifest():
    """InniSync's record of what it put on the Y1. No record = a Y1 InniSync hasn't synced yet."""
    if not exists(MANIFEST):
        return json.loads(json.dumps(EMPTY_MANIFEST))
    try:
        data = json.loads(adb("shell", f"cat {q(MANIFEST)}", timeout=60))
    except (ValueError, DeviceError) as e:
        raise ManifestError(f"InniSync couldn't read its record of what's on the Y1, so it changed nothing. "
                            f"Unplug the Y1, plug it back in and try again. ({e})")
    if not isinstance(data, dict) or not isinstance(data.get("songs"), dict):
        raise ManifestError("InniSync's record of what's on the Y1 is damaged, so it changed nothing. "
                            f"It's at {MANIFEST}; a backup of the Y1 doesn't include it.")
    return data


def write_manifest(man):
    """Written next to the real one and renamed into place, so an interrupted write never leaves half a record."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(man, f)
        tmp = f.name
    try:
        push(tmp, MANIFEST + ".tmp")
        shell_ok(f"mv {q(MANIFEST + '.tmp')} {q(MANIFEST)}")
    finally:
        os.unlink(tmp)


SHELL_MAX = 880  # the Y1's old adb refuses longer shell lines ("shell command too long"); shell_ok adds 15


def _batched(cmd, paths, timeout):
    """Run `cmd path path ...` in as many calls as it takes to keep each line under SHELL_MAX; raises if one fails."""
    line = cmd
    for p in paths:
        arg = " " + q(p)
        if line != cmd and len(line) + len(arg) > SHELL_MAX:
            shell_ok(line, timeout=timeout)
            line = cmd
        line += arg
    if line != cmd:
        shell_ok(line, timeout=timeout)


def mkdirs(paths):
    _batched("mkdir -p", paths, 60)


def push(local, remote):
    adb("push", local, remote, timeout=1800)


def push_whole(local, remote):
    """Push under a temporary name, then rename: a copy cut short never sits at the real path looking finished
    (InniClassic treats a podcast file at its path as downloaded). A rename keeps the file's date."""
    push(local, remote + ".part")
    shell_ok(f"mv {q(remote + '.part')} {q(remote)}")


def pull(remote, local, timeout=600):
    """Copy a file or folder off the Y1. A folder lands AT `local` (which must not exist yet)."""
    adb("pull", remote, local, timeout=timeout)


def exists(path):
    return shell(f"[ -e {q(path)} ] && echo yes").strip() == "yes"


def packages():
    """`pm list packages -f` lines (package:<apk path>=<name>), plus the names of user-installed ones."""
    every = sorted(l.strip() for l in shell("pm list packages -f", timeout=60).splitlines() if l.startswith("package:"))
    user = sorted(l.strip().removeprefix("package:") for l in shell("pm list packages -3", timeout=60).splitlines()
                  if l.startswith("package:"))
    return every, user


def installed_apk(pkg=None):
    """Path of the APK Android runs for pkg (the updated copy in /data/app if there is one)."""
    m = re.search(r"package:(\S+)", shell(f"pm path {pkg or LAUNCHER}"))
    return m.group(1) if m else None


def app_owner(pkg=None):
    """(uid, gid) that owns the app's data folder."""
    pkg = pkg or LAUNCHER
    m = re.search(r"^\S+\s+(\d+)\s+(\d+)", shell(f"ls -ldn /data/data/{pkg}"))
    if not m:
        raise DeviceError(f"{pkg} isn't installed on the Y1")
    return m.groups()


def install_apk(local):
    """`adb install -r`: replace the app in place, keeping its data. Raises InstallError with Android's reason."""
    p = subprocess.run([ADB, *(["-s", _transport] if _transport else []), "install", "-r", local],
                       capture_output=True, text=True, timeout=600)
    out = (p.stdout + p.stderr).replace("\r", "")
    m = re.search(r"Failure \[([A-Z_]+)", out)
    if m:
        raise InstallError(m.group(1), out)
    if p.returncode != 0 or "Success" not in out:
        raise DeviceError(out.strip()[-300:] or "adb install failed")
    return out


def remove(paths):
    _batched("rm -f", paths, 120)
    # prune now-empty album/artist folders inside the sync dir only
    shell(f"for d in {q(SYNC_DIR)}/*/* {q(SYNC_DIR)}/*; do [ -d \"$d\" ] && rmdir \"$d\" 2>/dev/null; done; true")


def rescan_library():
    """Make InniClassic rebuild its library: drop the cache and restart it (it auto-scans an empty library)."""
    shell(f"am force-stop {LAUNCHER}; rm -f {q(LIBRARY_CACHE)}; "
          f"am start -a android.intent.action.MAIN -c android.intent.category.HOME -n {LAUNCHER}/{ACTIVITY}")


def fix_clock():
    import time
    shell(f"date -s {time.strftime('%Y%m%d.%H%M%S')}; setprop persist.sys.timezone {mac_timezone()}")


def mac_timezone():
    """This computer's timezone name (e.g. Europe/Berlin), from where /etc/localtime points."""
    real = os.path.realpath("/etc/localtime")
    return real.split("zoneinfo/", 1)[1] if "zoneinfo/" in real else "UTC"


def _cat_json(path):
    try:
        out = adb("shell", f"cat {q(path)} 2>/dev/null", timeout=60)
        return json.loads(out) if out.strip() else None
    except (ValueError, DeviceError):
        return None


def contents():
    """What's on the Y1, as InniClassic sees it: its library index + every playlist in Y1_Playlists.

    Returns {"songs": [{path, name, artist, albumArtist, album, genre, track, year}], "playlists": [{name, paths}],
    "indexed": bool}. Songs missing from InniClassic's index (not rescanned yet) still appear via the playlists.
    """
    cache = _cat_json(LIBRARY_CACHE) or {}
    songs = []
    for it in cache.get("music", []):
        def clean(v, unknown):
            v = (v or "").strip()
            return "" if v.startswith("Unknown ") or v == unknown else v
        songs.append({
            "path": it.get("path", ""),
            "name": it.get("title") or os.path.splitext(os.path.basename(it.get("path", "")))[0],
            "artist": clean(it.get("artist"), ""),
            "albumArtist": clean(it.get("albumArtist"), ""),
            "album": clean(it.get("album"), ""),
            "genre": clean(it.get("genre"), "").strip("()") if not (it.get("genre") or "").startswith("(") else "",
            "track": it.get("trackNum"),
            "year": None if str(it.get("year", "")).startswith("Unknown") else it.get("year"),
        })
    playlists = []
    listing = shell(f"ls {q(PLAYLIST_DIR)} 2>/dev/null").splitlines()
    for name in sorted(n.strip() for n in listing if n.strip().lower().endswith((".m3u", ".m3u8"))):
        try:
            text = adb("shell", f"cat {q(PLAYLIST_DIR + '/' + name)}", timeout=30).replace("\r", "")
        except DeviceError:
            continue
        paths = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.replace("\\", "/")
            paths.append(line if line.startswith("/") else f"{SD}/Music/{line}")
        playlists.append({"name": os.path.splitext(name)[0].removeprefix(PLAYLIST_PREFIX), "paths": paths})
    return {"songs": songs, "playlists": playlists, "indexed": bool(cache)}


def cat_bytes(path):
    """Raw bytes of one file on the Y1 (this adbd predates exec-out, so it goes through adb pull)."""
    with tempfile.TemporaryDirectory(prefix="innisync-pull-") as d:
        local = os.path.join(d, "f")
        adb("pull", path, local, timeout=120)
        return open(local, "rb").read()


def restart_player():
    shell(f"am start -a android.intent.action.MAIN -c android.intent.category.HOME -n {LAUNCHER}/{ACTIVITY}")


# ---- InniClassic settings (its SharedPreferences file, edited while the app is stopped) ----
def _parse_prefs(xml_text):
    import xml.etree.ElementTree as ET
    out = {}
    if not xml_text.strip():
        return out
    for el in ET.fromstring(xml_text):
        name = el.get("name")
        if el.tag == "boolean":
            out[name] = el.get("value") == "true"
        elif el.tag in ("int", "long"):
            out[name] = int(el.get("value"))
        elif el.tag == "float":
            out[name] = float(el.get("value"))
        elif el.tag == "string":
            out[name] = el.text or ""
    return out


def player_prefs():
    return _parse_prefs(shell(f"cat {q(PLAYER_PREFS)} 2>/dev/null"))


def set_player_prefs(changes):
    """Write InniClassic settings. changes: {key: bool|int|str|None (None removes)}.

    InniClassic only reads its settings when it starts, and rewrites the whole file when it saves, so it is
    stopped first, the file is edited, then the player is started again (this stops anything playing).
    """
    import xml.etree.ElementTree as ET
    shell(f"am force-stop {LAUNCHER}")
    text = shell(f"cat {q(PLAYER_PREFS)} 2>/dev/null")
    root = ET.fromstring(text) if text.strip() else ET.Element("map")
    for key, val in changes.items():
        for el in [e for e in root if e.get("name") == key]:
            root.remove(el)
        if val is None:
            continue
        if isinstance(val, bool):
            el = ET.SubElement(root, "boolean", name=key, value="true" if val else "false")
        elif isinstance(val, int):
            el = ET.SubElement(root, "int", name=key, value=str(val))
        else:
            el = ET.SubElement(root, "string", name=key)
            el.text = str(val)
    body = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n" + ET.tostring(root, encoding="unicode")
    owner = re.search(r"^\S+\s+(\d+)\s+(\d+)", shell(f"ls -ln {q(PLAYER_PREFS)} 2>/dev/null"))
    uid, gid = owner.groups() if owner else app_owner()  # first run: the app's data folder owner
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(body)
        tmp = f.name
    try:
        push(tmp, "/data/local/tmp/innisync_prefs.xml")
    finally:
        os.unlink(tmp)
    shell_ok(f"cat /data/local/tmp/innisync_prefs.xml > {q(PLAYER_PREFS)} && chown {uid}:{gid} {q(PLAYER_PREFS)} && "
             f"chmod 660 {q(PLAYER_PREFS)}; rc=$?; rm -f /data/local/tmp/innisync_prefs.xml; [ $rc = 0 ]")
    restart_player()


# ---- themes ----
def _folder_configs(root):
    """{folder: config.json text} for every theme folder under root, in one adb call."""
    out = shell(f'for d in {q(root)}/*/; do [ -f "$d/config.json" ] && echo "@@YT@@$d" && cat "$d/config.json" && echo; done 2>/dev/null',
                timeout=60)
    found = {}
    for chunk in out.split("@@YT@@")[1:]:
        head, _, body = chunk.partition("\n")
        found[head.rstrip("/").rsplit("/", 1)[-1]] = body.lstrip("\ufeff")
    return found


def _files(root):
    """{folder: [file names]} one level down, for spotting covers and wallpapers."""
    out = shell(f'for d in {q(root)}/*/; do echo "@@YT@@$d"; ls "$d"; done 2>/dev/null', timeout=60)
    found = {}
    for chunk in out.split("@@YT@@")[1:]:
        head, _, body = chunk.partition("\n")
        found[head.rstrip("/").rsplit("/", 1)[-1]] = [l.strip() for l in body.splitlines() if l.strip()]
    return found


def inni_themes():
    """InniClassic themes on the Y1, plus which one is in use (InniClassic falls back to "iPod Classic")."""
    files = _files(INNI_THEMES)
    themes = [{"folder": None, "name": "Dark (Default)", "builtin": True, "colors": {}, "bg": None}]
    for folder, text in sorted(_folder_configs(INNI_THEMES).items(), key=lambda kv: kv[0].lower()):
        try:
            cfg = json.loads(text)
        except ValueError:
            continue
        names = files.get(folder, [])
        bg = cfg.get("bg_image") if cfg.get("bg_image") in names else next((n for n in ("background.png", "bg.png") if n in names), None)
        themes.append({"folder": folder, "name": cfg.get("name") or folder, "builtin": False, "bg": bg and f"{INNI_THEMES}/{folder}/{bg}",
                       "colors": {k: cfg.get(k) for k in ("textPrimary", "textSecondary", "bgOverlay", "statusBarBg", "btnFocused", "btnFocusedText")}})
    current = player_prefs().get("app_theme_name") or "iPod Classic"
    return {"themes": themes, "current": current}


def use_inni_theme(name):
    themes = inni_themes()["themes"]
    idx = next((i for i, t in enumerate(themes) if t["name"] == name), None)
    if idx is None:
        raise DeviceError(f"There's no theme called {name} on the Y1")
    changes = {"app_theme_name": name, "app_theme_index": idx}
    if themes[idx]["bg"]:  # same as picking it on the Y1: the theme's own wallpaper comes with it
        changes["bg_path"] = "THEME_DEFAULT"
    set_player_prefs(changes)


def stock_themes():
    files = _files(STOCK_THEMES)
    out = []
    for folder, text in sorted(_folder_configs(STOCK_THEMES).items(), key=lambda kv: kv[0].lower()):
        try:
            cfg = json.loads(text)
        except ValueError:
            cfg = {}
        names = files.get(folder, [])
        cover = cfg.get("themeCover") if cfg.get("themeCover") in names else next((n for n in names if "cover" in n.lower() and n.lower().endswith(IMAGE_EXT)), None)
        info = cfg.get("theme_info") or {}
        out.append({"folder": folder, "name": info.get("title") or folder, "author": info.get("author") or "",
                    "cover": cover and f"{STOCK_THEMES}/{folder}/{cover}"})
    return out


def push_folder(local_dir, remote_dir):
    shell(f"rm -rf {q(remote_dir)}; mkdir -p {q(os.path.dirname(remote_dir))}")
    adb("push", local_dir, remote_dir, timeout=900)


def remove_folder(root, folder):
    if not folder or "/" in folder or folder in (".", ".."):
        raise DeviceError("Not a theme folder")
    shell(f"rm -rf {q(root + '/' + folder)}")


# ---- audiobooks ----
LOOSE_BOOKS = "(loose files)"   # files straight in Audiobooks, listed as one book


def audiobooks():
    """[{book, files:[{name, size}]}]: each folder in Audiobooks is one book (chapters play in name order)."""
    # toolbox ls -l prints bare names, so walk ls -lR and track the "<dir>:" headers
    out = shell(f"ls -lR {q(AUDIOBOOKS)} 2>/dev/null", timeout=60)
    books, cur = {}, AUDIOBOOKS
    for line in out.splitlines():
        line = line.rstrip()
        if line.endswith(":") and line.startswith("/"):
            cur = line[:-1]
            continue
        m = re.match(r"-\S+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+(.+)$", line)
        if not m:
            continue
        rel = cur[len(AUDIOBOOKS):].strip("/")
        books.setdefault(rel or LOOSE_BOOKS, []).append({"name": m.group(2), "size": int(m.group(1)), "path": f"{cur}/{m.group(2)}"})
    return [{"book": b, "files": sorted(f, key=lambda x: x["name"].lower())} for b, f in sorted(books.items(), key=lambda kv: kv[0].lower())]


def remove_book(book):
    """Remove exactly the files the Audiobooks list shows for `book` (a folder's own files, or the loose ones at the
    top), then its folder if that leaves it empty. A folder holding other books keeps them."""
    files = next((b["files"] for b in audiobooks() if b["book"] == book), None)
    if not files:
        raise DeviceError("That book isn't on the Y1")
    _batched("rm -f", [f["path"] for f in files], 120)
    if book != LOOSE_BOOKS:
        shell(f"rmdir {q(AUDIOBOOKS + '/' + book)} 2>/dev/null; true")
