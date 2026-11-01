"""The Y1's player app, iTunes-style: check GitHub for a newer release, download it, check its digest and signer,
back up the Y1, then `adb install -r` it in place. Two player apps are known (PLAYERS): InniClassic, and InniClassic
Autoplay (InniSync's build of it, a separate package). A Y1 on InniClassic can switch to Autoplay: it is installed
beside the original, takes a copy of the original's settings, and the original is disabled (not removed, so its
settings stay) so Autoplay is the Y1's only home app. Switching back enables the original and disables Autoplay.

Each app's releases are signed with one key, so installing over the old copy keeps its settings. If Android ever says
INSTALL_FAILED_UPDATE_INCOMPATIBLE (a different key), InniSync stops: getting past that means uninstalling, which
erases the player's settings, and that's the owner's call, not ours.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

from . import backup, device, sync, tools

PLAYERS = {
    device.ORIGINAL: {"name": "InniClassic", "repo": "FabianZettl/inniclassic", "asset": r"InniClassic-[\d.]+\.apk"},
    device.AUTOPLAY: {"name": "InniClassic Autoplay", "repo": "johnnmoody/inniclassic-autoplay",
                      "asset": r"InniClassic-Autoplay-[\d.]+-autoplay\d+\.apk"},
}
APK_DIR = os.path.join(sync.APP_DIR, "updates")
CHECK_EVERY = 24 * 3600
INCOMPATIBLE = "INSTALL_FAILED_UPDATE_INCOMPATIBLE"

_cache = {}   # package -> {"at", "release"}


def _ver(v):
    return [int(x) for x in re.findall(r"\d+", v or "")]


def latest_release(pkg, force=False):
    """Newest release of that player app with an APK: {pkg, app, version, name, url, size, sha256, published, page}."""
    hit = _cache.get(pkg)
    if not force and hit and time.time() - hit["at"] < CHECK_EVERY:
        return hit["release"]
    app = PLAYERS[pkg]
    req = urllib.request.Request(f"https://api.github.com/repos/{app['repo']}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "InniSync"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rel = json.load(r)
    asset = next((a for a in rel.get("assets", []) if re.fullmatch(app["asset"], a["name"])), None)
    if not asset:
        raise device.DeviceError(f"{app['name']} {rel.get('tag_name')} has no APK to install")
    digest = asset.get("digest") or ""
    release = {"pkg": pkg, "app": app["name"], "version": rel["tag_name"].lstrip("v"), "name": asset["name"],
               "url": asset["browser_download_url"], "size": asset["size"],
               "sha256": digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
               "published": rel.get("published_at"), "page": rel.get("html_url")}
    _cache[pkg] = {"at": time.time(), "release": release}
    return release


def check(installed, force=False):
    """What the Summary tab says about the Y1's player app, and whether Update (or Switch) has something to do."""
    pkg = device.LAUNCHER
    rel = latest_release(pkg, force)
    name = PLAYERS[pkg]["name"]
    newer = bool(installed) and _ver(rel["version"]) > _ver(installed)
    next_check = time.strftime("%A, %B %-d", time.localtime(_cache[pkg]["at"] + CHECK_EVERY))
    if not installed:
        msg = f"InniClassic isn't installed on your Y1. The latest version is {rel['version']}."
    elif newer:
        msg = (f"A newer version of the Y1 software is available ({name} {rel['version']}). You may update "
               f"your Y1 to the latest version by clicking on the Update button.")
    else:
        msg = (f"Your Y1 software ({name} {installed}) is up to date. InniSync will automatically check for an "
               f"update again on {next_check}.")
    out = {"app": name, "latest": rel["version"], "installed": installed, "update": newer, "message": msg,
           "published": rel["published"], "page": rel["page"]}
    if installed and pkg == device.ORIGINAL:   # offer InniSync's build: same player, plus Autoplay
        try:
            alt = latest_release(device.AUTOPLAY, force)
            out["autoplay"] = {"version": alt["version"], "page": alt["page"],
                               "installed": device.package_installed(device.AUTOPLAY)}
        except Exception:
            pass   # no offer this time; the update check itself still answers
    return out


def download(rel, progress=lambda done, total: None):
    """The release APK in APK_DIR, verified against GitHub's sha256 digest (reused if already downloaded)."""
    if not rel["sha256"]:
        raise device.DeviceError(f"GitHub gave no checksum for {rel['name']}, so InniSync won't install it")
    os.makedirs(APK_DIR, exist_ok=True)
    path = os.path.join(APK_DIR, rel["name"])
    if os.path.exists(path) and _sha256(path) == rel["sha256"]:
        progress(rel["size"], rel["size"])
        return path
    h, done = hashlib.sha256(), 0
    req = urllib.request.Request(rel["url"], headers={"User-Agent": "InniSync"})
    with urllib.request.urlopen(req, timeout=60) as r, open(path + ".part", "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, rel["size"])
    if h.hexdigest() != rel["sha256"]:
        os.remove(path + ".part")
        raise device.DeviceError(f"{rel['name']} didn't match GitHub's checksum, so it was thrown away")
    os.replace(path + ".part", path)
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def apk_info(path):
    """{package, version, signer}: signer is the SHA-256 of the signing certificate (None if the tools are missing)."""
    out = {"package": None, "version": None, "signer": None}
    aapt2, apksigner, jdk = tools.build_tool("aapt2"), tools.build_tool("apksigner"), tools.java_home()
    if aapt2:
        head = subprocess.run([aapt2, "dump", "badging", path], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"package: name='([^']+)'.*?versionName='([^']*)'", head)
        if m:
            out["package"], out["version"] = m.groups()
    if apksigner and jdk:
        env = {**os.environ, "JAVA_HOME": jdk, "PATH": f"{jdk}/bin:" + os.environ.get("PATH", "")}
        certs = subprocess.run([apksigner, "verify", "--print-certs", path], capture_output=True, text=True,
                               timeout=120, env=env).stdout
        m = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", certs)
        out["signer"] = m.group(1) if m else None
    return out


def preflight(apk, rel):
    """Check the download is the app we expect and signed like the copy on the Y1 (if there is one), before touching
    anything."""
    new = apk_info(apk)
    if new["package"] and new["package"] != rel["pkg"]:
        raise device.DeviceError(f"{rel['name']} is {new['package']}, not {rel['app']}")
    if new["version"] and new["version"] != rel["version"]:
        raise device.DeviceError(f"{rel['name']} says it's version {new['version']}, not {rel['version']}")
    have = None
    remote = device.installed_apk(rel["pkg"])
    if remote and new["signer"]:
        local = os.path.join(APK_DIR, "installed.apk")
        device.pull(remote, local, timeout=300)
        try:
            have = apk_info(local)["signer"]
        finally:
            os.remove(local)
    if have and new["signer"] != have:
        raise device.InstallError(INCOMPATIBLE, "signing certificates differ")
    return {"apk": apk, "signer": new["signer"], "installed_signer": have, "same_signer": have == new["signer"] if have else None}


def incompatible_message(rel):
    return (f"{rel['app']} {rel['version']} is signed with a different key than the copy on your Y1, so it can't be "
            f"installed over it. InniSync left your Y1 as it was. Installing it would mean removing {rel['app']} first, "
            f"which erases its settings: back up first, then do that by hand if you want to.")


class UpdateJob:
    """Download, verify, back up, install. With switch=True, a Y1 on InniClassic gets InniClassic Autoplay instead
    (see the module notes). dry_run stops after the checks and says what it would do."""
    ACTIVE = ("starting", "downloading", "verifying", "backing_up", "installing")

    def __init__(self, info, dry_run=False, switch=False):
        self.info, self.dry_run, self.switch = info, dry_run, switch
        self.status = {"state": "starting", "message": "Checking for the latest version", "done": 0, "total": 0,
                       "dryRun": dry_run}

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _set(self, **kw):
        self.status = {**self.status, **kw}   # a new dict, so the server never serializes one mid-change

    def _run(self):
        rel = None
        try:
            if self.switch and device.LAUNCHER != device.ORIGINAL:
                return self._set(state="done", message="Your Y1 already runs InniClassic Autoplay")
            pkg = device.AUTOPLAY if self.switch else device.LAUNCHER
            rel = latest_release(pkg, force=True)
            if not self.switch and not self.dry_run and _ver(rel["version"]) <= _ver(self.info.get("launcher")):
                return self._set(state="done", message=f"Your Y1 already has {rel['app']} {self.info.get('launcher')}")
            what = f"{rel['app']} {rel['version']}"
            self._set(state="downloading", message=f"Downloading {what}", total=rel["size"])
            apk = download(rel, lambda d, t: self._set(done=d, total=t))
            self._set(state="verifying", message="Verifying the download")
            check = preflight(apk, rel)
            if self.dry_run:
                signer = {True: "same signer as the installed copy", False: "different signer",
                          None: "signer not compared"}[check["same_signer"]]
                then = ", copy the player's settings to it, and make it the Y1's player" if self.switch else ""
                return self._set(state="done", message=f"Ready to install {what} (checksum OK, {signer}). "
                                 f"Would run: adb install -r {os.path.basename(apk)}{then}", preflight=check)
            self._set(state="backing_up", message="Backing up the Y1")
            b = backup.create(self.info, reason=f"before {what}")
            backup.prune(self.info["serial"])
            self._set(state="installing", message=f"Installing {what}", backup=b["name"])
            device.install_apk(apk)
            if self.switch:
                device.switch_player(device.AUTOPLAY)
                device.set_player_prefs({"autoplay": True})   # the reason to switch; it can be turned off in Settings
                return self._set(state="done", installed=rel["version"],
                                 message=f"Your Y1 now plays with {what}, with your settings. Autoplay is on.")
            device.restart_player()
            self._set(state="done", message=f"Your Y1 now has {what}", installed=rel["version"])
        except device.InstallError as e:
            msg = incompatible_message(rel) if e.code == INCOMPATIBLE and rel else str(e)
            self._set(state="error", message=msg, code=e.code)
        except Exception as e:
            self._set(state="error", message=str(e))


# ---- Innioasis Updater CE: the community flasher, for anything beyond an InniClassic update ----
UPDATER_REPO = "y1-community/Innioasis-Updater"
UPDATER_ID = "com.innioasis.updater"
_updater = {"at": 0, "release": None}


def updater_app():
    """(path, version) of Innioasis Updater on this computer, or (None, None)."""
    found = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{UPDATER_ID}'"], capture_output=True, text=True,
                           timeout=20).stdout.split("\n")
    for path in [p for p in found if p.endswith(".app")] + ["/Applications/Innioasis Updater.app",
                                                             os.path.expanduser("~/Applications/Innioasis Updater.app")]:
        plist = os.path.join(path, "Contents", "Info.plist")
        if os.path.isfile(plist):
            import plistlib
            with open(plist, "rb") as f:
                return path, plistlib.load(f).get("CFBundleShortVersionString")
    return None, None


def updater_release(force=False):
    """Latest Updater CE release's Mac DMG: {tag, name, url, size, sha256}."""
    if not force and _updater["release"] and time.time() - _updater["at"] < CHECK_EVERY:
        return _updater["release"]
    req = urllib.request.Request(f"https://api.github.com/repos/{UPDATER_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "InniSync"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rel = json.load(r)
    dmg = next((a for a in rel.get("assets", []) if a["name"].endswith(".dmg")), None)
    if not dmg:
        raise device.DeviceError(f"Innioasis Updater {rel.get('tag_name')} has no Mac download")
    digest = dmg.get("digest") or ""
    _updater.update(at=time.time(), release={
        "tag": rel["tag_name"], "name": dmg["name"], "url": dmg["browser_download_url"], "size": dmg["size"],
        "sha256": digest.removeprefix("sha256:") if digest.startswith("sha256:") else None, "page": rel.get("html_url")})
    return _updater["release"]


def updater_status():
    path, version = updater_app()
    try:
        rel = updater_release()
    except Exception as e:
        rel = {"error": str(e)}
    return {"installed": bool(path), "path": path, "version": version, "latest": rel.get("tag"), "error": rel.get("error")}


def open_updater(info):
    """Back up the Y1 (if it's connected), then open Updater CE, or download its DMG and open that to install it.
    Returns {"opened": "app"|"dmg", "backup": name or None}."""
    b = None
    if info.get("connected"):
        b = backup.create(info, reason="before reflashing")["name"]
        backup.prune(info["serial"])
    path, _ = updater_app()
    if path:
        subprocess.run(["open", path], check=True, timeout=30)
        return {"opened": "app", "backup": b}
    rel = updater_release(force=True)
    dmg = download(rel | {"version": rel["tag"]})   # same checked download as InniClassic's APK
    subprocess.run(["open", dmg], check=True, timeout=60)
    return {"opened": "dmg", "backup": b, "tag": rel["tag"]}
