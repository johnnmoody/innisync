"""InniClassic updates, iTunes-style: check GitHub for a newer release, download it, check its digest and signer,
back up the Y1, then `adb install -r` it in place.

Every InniClassic release is signed with the same debug key, so installing over the old one keeps its settings.
If Android ever says INSTALL_FAILED_UPDATE_INCOMPATIBLE (a different key), InniSync stops: getting past that means
uninstalling, which erases the player's settings, and that's the owner's call, not ours.
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

REPO = "FabianZettl/inniclassic"
APK_DIR = os.path.join(sync.APP_DIR, "updates")
CHECK_EVERY = 24 * 3600
INCOMPATIBLE = "INSTALL_FAILED_UPDATE_INCOMPATIBLE"

_cache = {"at": 0, "release": None}


def _ver(v):
    return [int(x) for x in re.findall(r"\d+", v or "")]


def latest_release(force=False):
    """Newest InniClassic release with an APK: {version, name, url, size, sha256, published, page}."""
    if not force and _cache["release"] and time.time() - _cache["at"] < CHECK_EVERY:
        return _cache["release"]
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "InniSync"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rel = json.load(r)
    asset = next((a for a in rel.get("assets", []) if re.fullmatch(r"InniClassic-[\d.]+\.apk", a["name"])), None)
    if not asset:
        raise device.DeviceError(f"InniClassic {rel.get('tag_name')} has no APK to install")
    digest = asset.get("digest") or ""
    _cache.update(at=time.time(), release={
        "version": rel["tag_name"].lstrip("v"), "name": asset["name"], "url": asset["browser_download_url"],
        "size": asset["size"], "sha256": digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
        "published": rel.get("published_at"), "page": rel.get("html_url")})
    return _cache["release"]


def check(installed, force=False):
    rel = latest_release(force)
    newer = bool(installed) and _ver(rel["version"]) > _ver(installed)
    next_check = time.strftime("%A, %B %-d", time.localtime(_cache["at"] + CHECK_EVERY))
    if device.LAUNCHER == device.AUTOPLAY:
        # InniSync's own build: GitHub's APK is the plain player under another package, so it isn't installed over it
        msg = (f"Your Y1 runs InniClassic Autoplay {installed}, InniSync's build of the player. "
               + (f"InniClassic {rel['version']} is out: rebuild InniClassic Autoplay from it to update."
                  if _ver(rel["version"]) > _ver(installed.split("-")[0]) else "It's based on the latest InniClassic."))
        newer = False
    elif not installed:
        msg = f"InniClassic isn't installed on your Y1. The latest version is {rel['version']}."
    elif newer:
        msg = (f"A newer version of the Y1 software is available (InniClassic {rel['version']}). You may update "
               f"your Y1 to the latest version by clicking on the Update button.")
    else:
        msg = (f"Your Y1 software (InniClassic {installed}) is up to date. InniSync will automatically check for an "
               f"update again on {next_check}.")
    return {"latest": rel["version"], "installed": installed, "update": newer, "message": msg,
            "published": rel["published"], "page": rel["page"]}


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
    """Check the download is the InniClassic we expect and signed like the copy on the Y1, before touching it."""
    new = apk_info(apk)
    if new["package"] and new["package"] != device.LAUNCHER:
        raise device.DeviceError(f"{rel['name']} is {new['package']}, not InniClassic")
    if new["version"] and new["version"] != rel["version"]:
        raise device.DeviceError(f"{rel['name']} says it's version {new['version']}, not {rel['version']}")
    have = None
    remote = device.installed_apk()
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


def incompatible_message(version):
    return (f"InniClassic {version} is signed with a different key than the copy on your Y1, so it can't be "
            f"installed over it. InniSync left your Y1 as it was. Installing it would mean removing InniClassic first, "
            f"which erases its settings: back up first, then do that by hand if you want to.")


class UpdateJob:
    """Download, verify, back up, install. dry_run stops after the checks and says what it would run."""
    ACTIVE = ("starting", "downloading", "verifying", "backing_up", "installing")

    def __init__(self, info, dry_run=False):
        self.info, self.dry_run = info, dry_run
        self.status = {"state": "starting", "message": "Checking for the latest version", "done": 0, "total": 0,
                       "dryRun": dry_run}

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _set(self, **kw):
        self.status.update(kw)

    def _run(self):
        try:
            if device.LAUNCHER == device.AUTOPLAY:
                return self._set(state="error", message="Your Y1 runs InniClassic Autoplay; it updates by being rebuilt, not from GitHub.")
            rel = latest_release(force=True)
            if not self.dry_run and _ver(rel["version"]) <= _ver(self.info.get("launcher")):
                return self._set(state="done", message=f"Your Y1 already has InniClassic {self.info.get('launcher')}")
            self._set(state="downloading", message=f"Downloading InniClassic {rel['version']}", total=rel["size"])
            apk = download(rel, lambda d, t: self._set(done=d, total=t))
            self._set(state="verifying", message="Verifying the update")
            check = preflight(apk, rel)
            if self.dry_run:
                signer = {True: "same signer as the installed copy", False: "different signer",
                          None: "signer not compared"}[check["same_signer"]]
                return self._set(state="done", message=f"Ready to install InniClassic {rel['version']} "
                                 f"(checksum OK, {signer}). Would run: adb install -r {os.path.basename(apk)}",
                                 preflight=check)
            self._set(state="backing_up", message="Backing up the Y1")
            b = backup.create(self.info, reason=f"before InniClassic {rel['version']}")
            backup.prune(self.info["serial"])
            self._set(state="installing", message=f"Installing InniClassic {rel['version']}", backup=b["name"])
            device.install_apk(apk)
            device.restart_player()
            self._set(state="done", message=f"Your Y1 now has InniClassic {rel['version']}", installed=rel["version"])
        except device.InstallError as e:
            msg = incompatible_message(_cache["release"]["version"]) if e.code == INCOMPATIBLE else str(e)
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
