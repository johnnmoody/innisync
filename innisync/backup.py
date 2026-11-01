"""Back up and restore the Y1's own data: InniClassic's settings, its playlists, its library index and play log.

A backup is a folder <timestamp>/ holding shared_prefs/, Y1_Playlists/, .y1_library_cache.json, .scrobbler.log,
packages.txt and info.json. They go to the backup folder chosen in Preferences (a NAS or external drive, say) when
it's there, else to Application Support.
Restore only puts back settings and playlists: the library index and play log are kept for reference, since the
Y1 rebuilds the index itself and the log only grows.
"""
import datetime
import glob
import json
import os
import shutil
import tempfile
import time

from . import device, sync

LOCAL_ROOT = os.path.join(sync.APP_DIR, "backups")
KEEP_AUTOMATIC = 20      # newest automatic backups kept per Y1; ones made with Back Up are never pruned
RECENT = 3600            # a connect within an hour of the last backup doesn't make another
FILES = [(device.LIBRARY_CACHE, ".y1_library_cache.json"), (device.SCROBBLER_LOG, ".scrobbler.log")]


_folder = [None]   # the backup folder from Preferences; the server sets it


def set_folder(path):
    _folder[0] = os.path.expanduser(path) if path else None


def chosen_root():
    """The Preferences backup folder, if one is set and reachable right now (a network drive may not be mounted)."""
    f = _folder[0]
    return f if f and os.path.isdir(f) else None


def roots():
    return [r for r in (chosen_root(), LOCAL_ROOT) if r]


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)


def create(info, reason="manual"):
    """Back up the connected Y1. info = device.info(). Returns the backup's summary (see list_backups)."""
    root = chosen_root() or LOCAL_ROOT
    os.makedirs(root, exist_ok=True)
    name = time.strftime("%Y-%m-%d_%H%M%S")
    with tempfile.TemporaryDirectory(prefix="innisync-backup-") as tmp:
        device.pull(device.PREFS_DIR, os.path.join(tmp, "shared_prefs"))
        if device.exists(device.PLAYLIST_DIR):
            device.pull(device.PLAYLIST_DIR, os.path.join(tmp, "Y1_Playlists"))
            os.makedirs(os.path.join(tmp, "Y1_Playlists"), exist_ok=True)  # an empty folder doesn't come across
        for remote, local in FILES:
            if device.exists(remote):
                device.pull(remote, os.path.join(tmp, local))
        every, user = device.packages()
        with open(os.path.join(tmp, "packages.txt"), "w") as f:
            f.write("\n".join(every) + "\n")
        parts = {p: _size(os.path.join(tmp, p)) for p in sorted(os.listdir(tmp))}
        meta = {
            "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "reason": reason,
            "device": {k: info.get(k) for k in ("serial", "name", "model", "firmware", "android", "launcher")},
            "user_apps": user,
            "parts": parts,
            "playlists": sorted(os.listdir(os.path.join(tmp, "Y1_Playlists"))) if "Y1_Playlists" in parts else [],
            "prefs": sorted(os.listdir(os.path.join(tmp, "shared_prefs"))),
        }
        with open(os.path.join(tmp, "info.json"), "w") as f:
            json.dump(meta, f, indent=2)
        # copied under a .partial name first, so a backup cut short never shows up in the list
        dest, n = os.path.join(root, name), 1
        while os.path.exists(dest) or os.path.exists(dest + ".partial"):   # two backups in the same second
            n += 1
            dest = os.path.join(root, f"{name}-{n}")
        shutil.copytree(tmp, dest + ".partial")
        os.rename(dest + ".partial", dest)
    return _summary(dest)


def _summary(path):
    with open(os.path.join(path, "info.json")) as f:
        meta = json.load(f)
    return {"path": path, "name": os.path.basename(path), "created": meta["created"], "reason": meta.get("reason"),
            "device": meta.get("device", {}), "playlists": len(meta.get("playlists", [])),
            "hasPlaylists": "Y1_Playlists" in meta.get("parts", {}), "prefs": meta.get("prefs", []),
            "size": sum(meta.get("parts", {}).values()),
            "where": "this computer" if path.startswith(LOCAL_ROOT) else os.path.basename(os.path.dirname(path)) or "Backup folder"}


def list_backups(serial=None):
    out = []
    for root in roots():
        for path in glob.glob(os.path.join(root, "*", "info.json")):
            try:
                b = _summary(os.path.dirname(path))
            except (OSError, ValueError, KeyError):
                continue
            if not serial or b["device"].get("serial") in (serial, None):
                out.append(b)
    return sorted(out, key=lambda b: b["created"], reverse=True)


def prune(serial, keep=KEEP_AUTOMATIC):
    """Delete the oldest automatic backups of this Y1 beyond `keep`. Returns how many went."""
    auto = [b for b in list_backups(serial) if b["reason"] != "manual"]
    for b in auto[keep:]:
        shutil.rmtree(b["path"])
    return max(len(auto) - keep, 0)


def auto_backup(info):
    """The backup made when the Y1 connects: skipped if one was made in the last hour. Returns it, or None."""
    newest = next(iter(list_backups(info["serial"])), None)
    if newest and time.time() - datetime.datetime.fromisoformat(newest["created"]).timestamp() < RECENT:
        return None
    b = create(info, reason="when connected")
    prune(info["serial"])
    return b


def _resolve(path):
    """Only folders inside a backups root with an info.json count; anything else is refused."""
    real = os.path.realpath(path or "")
    for root in roots():
        r = os.path.realpath(root)
        if os.path.dirname(real) == r and os.path.isfile(os.path.join(real, "info.json")):
            return real
    raise device.DeviceError("That backup wasn't found")


def restore(path, info, settings=True, playlists=True):
    """Put a backup's settings and/or playlists back on the Y1. The Y1 is backed up as it is first."""
    src = _resolve(path)
    if not (settings or playlists):
        raise device.DeviceError("Choose settings, playlists, or both to restore")
    safety = create(info, reason=f"before restoring {os.path.basename(src)}")
    device.shell(f"am force-stop {device.LAUNCHER}")
    try:
        if settings:
            _restore_prefs(os.path.join(src, "shared_prefs"))
        if playlists and os.path.isdir(os.path.join(src, "Y1_Playlists")):
            _restore_playlists(os.path.join(src, "Y1_Playlists"))
    finally:
        device.restart_player()
    return safety


def _restore_prefs(local):
    if not os.path.isdir(local) or not os.listdir(local):
        raise device.DeviceError("This backup has no player settings")
    uid, gid = device.app_owner()
    tmp, dest = "/data/local/tmp/innisync_restore_prefs", device.PREFS_DIR
    device.push_folder(local, tmp)
    # cat into place (no cp in this toolbox), then give each file back to the app
    device.shell_ok(f'rc=0; mkdir -p {dest} && chown {uid}:{gid} {dest} && chmod 771 {dest} || rc=1; '
                    f'for f in {tmp}/*; do n="${{f##*/}}"; {{ cat "$f" > "{dest}/$n" && chown {uid}:{gid} "{dest}/$n" && '
                    f'chmod 660 "{dest}/$n"; }} || rc=1; done; rm -rf {tmp}; [ $rc = 0 ]')


def _restore_playlists(local):
    # built next to the real folder, then swapped in, so a failed copy leaves the old playlists alone
    tmp = f"{device.SD}/.innisync_restore_playlists"
    if os.listdir(local):
        device.push_folder(local, tmp)
    else:
        device.shell(f"rm -rf {device.q(tmp)}; mkdir -p {device.q(tmp)}")
    device.shell_ok(f"rm -rf {device.q(device.PLAYLIST_DIR)} && mv {device.q(tmp)} {device.q(device.PLAYLIST_DIR)}")
