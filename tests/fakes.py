"""A pretend Y1 for tests: files kept in memory, and just enough of its adb shell (cat, ls, ls -lR, mv, rm -f, mkdir -p,
"[ -e path ] && echo yes", and `echo __RC=$?` for device.shell_ok) for the code under test. Install it with
FakeY1().install(monkeypatch). Set fail_on to a path to make every rm/mv touching it fail like a read-only card."""
import os
import re
import shlex

from innisync import device


class FakeY1:
    def __init__(self, files=None):
        self.files = dict(files or {})   # device path -> bytes
        self.pushed = []                  # remote paths written by push, in order
        self.fail_cat = False             # make every cat fail like a dropped adb connection
        self.fail_on = None               # a path whose rm/mv fails (exit status 1)
        self.removed = []                 # paths rm'd, in order
        self.rc = 0

    def install(self, monkeypatch):
        monkeypatch.setattr(device, "adb", self.adb)
        monkeypatch.setattr(device, "shell", lambda cmd, timeout=60: self.run(cmd))
        monkeypatch.setattr(device, "push", self.push)
        monkeypatch.setattr(device, "cat_bytes", lambda path: self.files[path])
        return self

    # ---- adb ----
    def adb(self, *args, timeout=60, check=True):
        if args[0] == "shell":
            return self.run(args[1])
        raise device.DeviceError(f"fake adb doesn't do {args[0]}")

    def push(self, local, remote):
        with open(local, "rb") as f:
            self.files[remote] = f.read()
        self.pushed.append(remote)

    # ---- a small shell ----
    def run(self, cmd):
        out = []
        for part in re.split(r"\s*;\s*|\s*&&\s*", cmd.strip()):
            if part:
                out.append(self._one(part.replace("$?", str(self.rc))))
        return "".join(out)

    def _dirs(self):
        d = set()
        for p in self.files:
            while "/" in p:
                p = p.rsplit("/", 1)[0]
                d.add(p)
        return d

    def _one(self, part):
        a = shlex.split(part.replace("2>/dev/null", ""))
        if a[:2] == ["[", "-e"]:
            self._last = a[2] in self.files or a[2] in self._dirs()
            return ""
        if a[0] == "echo":
            if a[1].startswith("__RC="):
                return a[1] + "\n"
            return (" ".join(a[1:]) + "\n") if getattr(self, "_last", True) else ""
        self.rc = 0
        if a[0] == "cat":
            if self.fail_cat:
                raise device.DeviceError("error: closed")
            return self.files[a[1]].decode("utf-8", "replace") if a[1] in self.files else ""
        if a[0] == "mv":
            if self.fail_on in (a[1], a[2]) or a[1] not in self.files:
                self.rc = 1
                return f"failed on '{a[1]}'\n"
            self.files[a[2]] = self.files.pop(a[1])
            return ""
        if a[0] == "rm":
            for p in a[2:] if a[1] == "-f" else a[1:]:
                if p == self.fail_on:
                    self.rc = 1
                    continue
                self.removed.append(p)
                self.files.pop(p, None)
            return ""
        if a[0] in ("true", "for", "am", "do", "done", "rmdir"):   # folder pruning loops and app restarts: nothing to model
            return ""
        if a[0] == "mkdir":
            return ""
        if a[0] == "ls" and a[1] == "-lR":
            return self._ls_lr(a[2])
        if a[0] == "ls":
            root = a[1].rstrip("/") + "/"
            names = sorted({p[len(root):].split("/")[0] for p in self.files if p.startswith(root)})
            return "".join(n + "\n" for n in names)
        raise AssertionError(f"fake Y1 shell doesn't know: {part}")

    def _ls_lr(self, root):
        """toolbox-style `ls -lR`: a "<dir>:" header, then one line per entry with the bare name last."""
        root = root.rstrip("/")
        out = []
        dirs = sorted(d for d in self._dirs() | {root} if d == root or d.startswith(root + "/"))
        for d in dirs:
            out.append(f"{d}:")
            for p, data in sorted(self.files.items()):
                if os.path.dirname(p) == d:
                    out.append(f"-rwxrwx--- media_rw media_rw {len(data)} 2026-10-31 20:04 {os.path.basename(p)}")
            for sub in sorted(x for x in dirs if os.path.dirname(x) == d):
                out.append(f"drwxrwx--- media_rw media_rw 2026-10-31 20:04 {os.path.basename(sub)}")
            out.append("")
        return "\n".join(out)


def song(i, name, artist, album, container="mp3", track=1, **kw):
    """A library song shaped like jellyfin.Jellyfin.songs() / subsonic.Subsonic.songs() return."""
    return {"id": i, "name": name, "artist": artist, "artists": [artist], "albumArtist": artist, "album": album,
            "albumId": "al-" + album, "genres": kw.get("genres", ["Pop"]), "year": kw.get("year", 2020),
            "track": track, "disc": kw.get("disc"), "duration": kw.get("duration", 200), "size": kw.get("size", 5_000_000),
            "container": container, "bitrate": 320000, "added": kw.get("added", "2026-10-01T00:00:00Z"),
            "lyrics": False, "plays": kw.get("plays", 0), "lastPlayed": kw.get("lastPlayed"), "favorite": False}
