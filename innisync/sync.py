"""iTunes-style one-way sync: Jellyfin selection -> Y1 (Music/InniSync + Y1_Playlists/*.m3u8)."""
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

from . import device, files, lyrics, playcounts, podcasts, tools
from .device import PLAYABLE, PLAYLIST_DIR, SD, SYNC_DIR
from .jellyfin import APP_DIR

FFMPEG = tools.find("ffmpeg", "INNISYNC_FFMPEG")
AUTOPLAY_MAP = f"{SD}/.innisync_autoplay.json"   # read by InniClassic Autoplay (the InniSync build of the player)
PLAYLIST_PREFIX = device.PLAYLIST_PREFIX
RESERVE = 1 << 30  # keep 1 GB free on the card
MP3_320_BYTES_PER_SEC = 40_000

DEFAULT_SETTINGS = {
    "sync_music": True,
    "mode": "selected",          # "all" | "selected"
    "playlists": [],             # Jellyfin playlist ids
    "artists": [],
    "genres": [],
    "fill_free": False,
    "convert": False,            # convert lossless to MP3 320
    "lyrics": True,              # copy timed lyrics (.lrc next to each song) for the Now Playing lyrics view
    "lyrics_lrclib": True,
    "play_counts": True,
    # iTunes' Podcasts tab: Sync Podcasts, Automatically include <rule> episodes of <all|selected> podcasts, plus picks
    "podcasts": {"sync": False, "auto": True, "rule": "3 most recent", "which": "all", "selected": [], "extra": []},         # count songs played on the Y1 in Jellyfin (from its .scrobbler.log)       # when Jellyfin has no timed lyrics for a song, look them up on LRCLIB
    "sync_mixes": True,          # write the mixes to the Y1
    "similar_seeds": [],         # song ids whose similar songs are kept on the Y1 as a playlist
}


def settings_path(serial):
    os.makedirs(APP_DIR, exist_ok=True)
    return os.path.join(APP_DIR, f"device_{serial}.json")


def load_settings(serial):
    try:
        return {**DEFAULT_SETTINGS, **files.read_json(settings_path(serial))}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def known_serials():
    """Every Y1 InniSync has sync settings for."""
    import glob
    return [os.path.basename(f)[7:-5] for f in glob.glob(os.path.join(APP_DIR, "device_*.json"))]


def save_settings(serial, s):
    clean = {k: s.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    files.write_json(settings_path(serial), clean, indent=1)
    return clean


def fat_safe(s, limit=80):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", s or "").strip().rstrip(". ")
    return re.sub(r"\s+", " ", s)[:limit] or "Unknown"


def target_ext(song, convert):
    c = song["container"]
    if c not in PLAYABLE or (convert and c in ("flac", "wav", "alac")):
        return "mp3"
    return "m4a" if c == "alac" else c


def device_path(song, convert):
    artist = fat_safe(song["albumArtist"] or song["artist"] or "Unknown Artist")
    album = fat_safe(song["album"] or "Unknown Album")
    num = f"{song['track']:02d} " if song.get("track") else ""
    if song.get("disc") and song["disc"] > 1:
        num = f"{song['disc']}-{num}"
    title = fat_safe(song["name"], 90)
    return f"{SYNC_DIR}/{artist}/{album}/{num}{title}.{target_ext(song, convert)}"


def rebuild_manifest(lib):
    """A new sync record from what's actually on the Y1, for when the old one is damaged: each library song whose file
    is where InniSync would have put it (as-is or converted) is claimed, with its lyrics. Anything else is left alone.
    Returns (manifest, number of files under Music/InniSync that matched no song)."""
    files, cur = {}, SYNC_DIR
    for line in device.shell(f"ls -lR {device.q(SYNC_DIR)} 2>/dev/null", timeout=120).splitlines():
        line = line.rstrip()
        if line.endswith(":") and line.startswith("/"):
            cur = line[:-1]
            continue
        m = re.match(r"-\S+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+(.+)$", line)
        if m and not m.group(2).startswith("."):
            # the card ignores case ("Lady GaGa" and "Lady Gaga" are one folder), so match the same way
            files[f"{cur}/{m.group(2)}".casefold()] = int(m.group(1))
    songs, claimed = {}, set()
    for i, s in lib.items():
        for conv in (False, True):
            path = device_path(s, conv)
            key = path.casefold()
            if key in files and key not in claimed:
                entry = {"path": path, "size": files[key]}   # recorded as sync names it, so the next plan matches
                lrc = os.path.splitext(path)[0] + ".lrc"
                if lrc.casefold() in files:
                    entry["lrc"] = lrc
                    claimed.add(lrc.casefold())
                songs[i] = entry
                claimed.add(key)
                break
    lists = [n.strip() for n in device.shell(f"ls {device.q(PLAYLIST_DIR)} 2>/dev/null").splitlines()
             if n.strip().startswith(PLAYLIST_PREFIX)]
    leftover = sum(1 for p in files if p not in claimed and not p.endswith(".lrc"))   # keys are casefolded
    return {"songs": songs, "playlists": lists, "podcasts": {}}, leftover


def est_size(song, convert):
    if target_ext(song, convert) == "mp3" and song["container"] != "mp3":
        return int(song["duration"] * MP3_320_BYTES_PER_SEC)
    return song["size"]


def selected_songs(lib, settings, playlist_items):
    """lib: {id: song}. playlist_items: {playlist_id: [song ids]}. Returns ordered list of song ids."""
    if not settings["sync_music"]:
        return []
    if settings["mode"] == "all":
        return list(lib)
    ids, seen = [], set()

    def add(i):
        if i in lib and i not in seen:
            seen.add(i)
            ids.append(i)

    for pid in settings["playlists"]:
        for i in playlist_items.get(pid, []):
            add(i)
    artists, genres = set(settings["artists"]), set(settings["genres"])
    for i, s in lib.items():
        if (s["albumArtist"] or s["artist"]) in artists or s["artist"] in artists or genres & set(s["genres"]):
            add(i)
    return ids


def _alt_path(path, song_id):
    """The name a song gets when another wanted song already has its path: the same name plus a short tag of its id."""
    base, ext = os.path.splitext(path)
    return f"{base} ({hashlib.sha1(song_id.encode()).hexdigest()[:6]}){ext}"


def resolve_paths(ids, lib, convert, have):
    """{id: device path} for songs going on the Y1, no two of them the same file. The card ignores case, so two
    untagged "Intro"s by one artist would share a path: one would overwrite the other and removing either would delete
    both. A song already on the Y1 keeps its file when that is still one of its names, so names stay put between
    syncs; otherwise the first song (in `ids` order) gets the plain name and the others the tagged one."""
    plain = {i: device_path(lib[i], convert) for i in ids}
    out, taken = {}, set()
    for i in ids:
        cur = have.get(i, {}).get("path")
        if cur and cur.casefold() in (plain[i].casefold(), _alt_path(plain[i], i).casefold()) and cur.casefold() not in taken:
            out[i] = cur
            taken.add(cur.casefold())
    for i in ids:
        if i not in out:
            path = plain[i] if plain[i].casefold() not in taken else _alt_path(plain[i], i)
            out[i] = path
            taken.add(path.casefold())
    return out


def plan(lib, settings, playlist_items, playlists, dev_info, manifest):
    """What a sync would do. `adds` are copied (new songs, and songs whose file name changes, e.g. when converting);
    `removes` are songs no longer wanted at all; `replaces` are songs in `adds` whose old file is deleted only after
    the new one is safely on the Y1."""
    conv = settings["convert"]
    have = manifest.get("songs", {})
    want = sorted(selected_songs(lib, settings, playlist_items))
    want_paths = resolve_paths(want, lib, conv, have)

    def diff():
        adds = [i for i in want_paths if have.get(i, {}).get("path") != want_paths[i]]
        removes = [i for i in have if i not in want_paths]
        replaces = [i for i in adds if have.get(i, {}).get("path")]
        return adds, removes, replaces
    adds, removes, replaces = diff()
    freed = lambda: sum(have[i].get("size", 0) for i in removes + replaces)
    budget = dev_info.get("free", 0) - RESERVE + freed()
    if settings["fill_free"] and settings["sync_music"] and settings["mode"] == "selected":
        room = budget - sum(est_size(lib[i], conv) for i in adds)
        pool = sorted(i for i in lib if i not in want_paths)
        random.Random(dev_info.get("serial", "y1")).shuffle(pool)
        fill = []
        for i in pool:
            sz = est_size(lib[i], conv)
            if sz <= room:
                fill.append(i)
                room -= sz
            if room < 50 << 20:
                break
        want_paths = resolve_paths(want + fill, lib, conv, have)
        adds, removes, replaces = diff()
        budget = dev_info.get("free", 0) - RESERVE + freed()
    add_bytes = sum(est_size(lib[i], conv) for i in adds)
    sel_pl = [p for p in playlists if p["id"] in settings["playlists"]] if settings["sync_music"] else []
    if settings["sync_music"] and settings["mode"] == "all":
        sel_pl = playlists
    return {
        "want": want_paths,
        "adds": adds,
        "removes": removes,
        "replaces": replaces,
        "add_bytes": add_bytes,
        "remove_bytes": freed(),
        "fits": add_bytes <= budget,
        "budget": budget,
        "playlists": sel_pl,
        "songs_after": len(want_paths),
        "bytes_after": dev_info.get("synced", 0) + add_bytes - freed(),
        "big_removal": big_removal(len(removes), len(have)),
    }


def big_removal(removing, on_y1):
    """A sync that would take most of the Y1's songs off is more likely a library that came back empty or cut short
    (server offline, rescanning, switched) than a real choice, so it waits for the user to confirm."""
    return removing >= 25 and removing > on_y1 / 2


class SyncJob:
    """Runs one sync in a background thread; .status is polled by the UI."""

    def __init__(self, jf, lib, settings, playlist_items, playlists, soundalike=None, autoplay=None, allow_removals=False):
        self.jf, self.lib, self.settings = jf, lib, settings
        self.allow_removals = allow_removals  # the user confirmed a sync that takes most songs off (see big_removal)
        self.playlist_items, self.playlists = playlist_items, playlists
        self.soundalike = soundalike  # callable(ids on the Y1) -> [{"name", "items", "kind"}] sound-alike playlists
        self.autoplay = autoplay  # callable(ids on the Y1) -> {id: [closest ids on the Y1]} for Autoplay
        self.status = {"state": "starting", "message": "Preparing to sync", "done": 0, "total": 0, "errors": []}
        self.cancel = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _set(self, **kw):
        self.status = {**self.status, **kw}   # a new dict, so the server never serializes one mid-change

    def _error(self, msg):
        self._set(errors=self.status["errors"] + [msg])

    def _send_play_counts(self, serial):
        try:
            r = playcounts.send(self.jf, self.lib, serial, playcounts.read_log(),
                                progress=lambda n, total: self._set(message=f"Updating play counts ({n} of {total})"),
                                cancel=lambda: self.cancel)
            self._set(plays=r)
        except Exception as e:
            self._error(f"Play counts: {e}")

    def _fetch(self, song, dest_ext, workdir):
        src = os.path.join(workdir, "src." + (song["container"] or "bin"))
        with self.jf.open_download(song["id"]) as r, open(src, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if dest_ext == song["container"] or (dest_ext == "m4a" and song["container"] == "alac"):
            return src
        out = os.path.join(workdir, "out." + dest_ext)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", src, "-map", "0:a:0", "-map", "0:v?",
                        "-c:a", "libmp3lame", "-b:a", "320k", "-c:v", "copy", "-id3v2_version", "3",
                        "-map_metadata", "0", out], check=True, timeout=600)
        return out

    def _run(self):
        try:
            info = device.info()
            if not info.get("connected"):
                raise device.DeviceError("The Y1 isn't connected")
            self._set(state="checking", message=f"Checking “{info['name']}”")
            if self.settings.get("play_counts", True):
                self._send_play_counts(info["serial"])
            if info.get("transport") == "wifi":
                # this Y1's Wi-Fi can't carry real data (see wifi.py), so a Wi-Fi sync is the play counts only
                sent = self.status.get("plays")
                if sent is None:   # the log didn't come across
                    return self._set(state="error", message="The Y1's Wi-Fi didn't carry the play log. Connect the Y1 by USB to sync.")
                return self._set(state="done", message=f"Sent {sent['sent']} play{'s' if sent['sent'] != 1 else ''} over Wi-Fi. "
                                 "Connect the Y1 by USB to sync music.")
            man = device.read_manifest()
            p = plan(self.lib, self.settings, self.playlist_items, self.playlists, info, man)
            if not p["fits"]:
                raise device.DeviceError("Not enough free space on the Y1 for this selection")
            if p["big_removal"] and not self.allow_removals:
                return self._set(state="error", code="removals", removing=len(p["removes"]),
                                 message=f"This sync would take {len(p['removes']):,} of the "
                                         f"{len(man.get('songs', {})):,} songs off the Y1, so nothing was changed.")
            conv = self.settings["convert"]
            adds = p["adds"]
            self._set(total=len(p["removes"]) + len(adds), state="syncing")
            songs = man.setdefault("songs", {})

            def files_of(i):
                return [f for f in (songs.get(i, {}).get("path"), songs.get(i, {}).get("lrc")) if f]

            def delete_unclaimed(paths):
                """Delete files no song still on the Y1 or being copied claims (a renamed song can take an old name)."""
                claimed = {f.casefold() for i, s in songs.items() for f in (s.get("path"), s.get("lrc")) if f}
                claimed |= {path.casefold() for path in p["want"].values()}
                doomed = [f for f in paths if f.casefold() not in claimed]
                if doomed:
                    device.remove(doomed)

            if p["removes"]:
                self._set(message="Removing songs")
                gone = [f for i in p["removes"] for f in files_of(i)]
                for i in p["removes"]:
                    songs.pop(i, None)
                delete_unclaimed(gone)
                self._set(done=self.status["done"] + len(p["removes"]))
                device.write_manifest(man)

            device.mkdirs(sorted({os.path.dirname(p["want"][i]) for i in adds}) + [PLAYLIST_DIR])
            last_save = time.time()
            with tempfile.TemporaryDirectory(prefix="innisync-") as work:
                for n, i in enumerate(adds, 1):
                    if self.cancel:
                        break
                    s = self.lib[i]
                    self._set(message=f"Copying {n} of {len(adds)}", current=f"{s['name']} — {s['artist']}")
                    try:
                        local = self._fetch(s, target_ext(s, conv), work)
                        device.push_whole(local, p["want"][i])
                        old = files_of(i)
                        songs[i] = {"path": p["want"][i], "size": os.path.getsize(local)}
                        for f in os.listdir(work):
                            os.unlink(os.path.join(work, f))
                        if old:   # the new file is on the Y1: now the old one can go
                            delete_unclaimed(old)
                    except Exception as e:  # keep going; the old file (if any) stays, and it's reported at the end
                        self._error(f"{s['artist']} - {s['name']}: {e}")
                    self._set(done=self.status["done"] + 1)
                    if time.time() - last_save > 30:
                        device.write_manifest(man)
                        last_save = time.time()
            device.write_manifest(man)
            if not self.cancel:
                self._sync_lyrics(songs)
                device.write_manifest(man)
            if not self.cancel:
                self._sync_podcasts(man)
                device.write_manifest(man)

            self._set(message="Updating playlists")
            self._write_playlists(p["playlists"], man)
            device.write_manifest(man)
            self._write_autoplay(man)
            self._set(message="Updating the Y1's library")
            device.rescan_library()
            errs = len(self.status["errors"])
            self._set(state="cancelled" if self.cancel else "done",
                      message="Sync cancelled" if self.cancel else
                      f"Synced, with {errs} problem{'s' if errs != 1 else ''}. OK to disconnect." if errs else
                      "Y1 sync is complete. OK to disconnect.")
        except device.ManifestError as e:
            self._set(state="error", message=str(e), code="manifest")
        except Exception as e:
            self._set(state="error", message=str(e))

    def _sync_podcasts(self, man):
        """Copy the episodes the Podcasts settings pick into InniClassic's Podcasts folders; remove ones InniSync copied
        that aren't picked any more. Episodes the Y1 downloaded itself are left alone."""
        mine = man.setdefault("podcasts", {})   # device path -> episode url, for files InniSync copied
        try:
            subs = podcasts.subscriptions()
        except Exception as e:
            self._error(f"Podcasts: {e}")
            return
        feeds = {}
        for s in subs if (self.settings.get("podcasts") or {}).get("sync") else []:
            self._set(message="Checking podcasts", current=s["name"])
            try:
                feeds[s["url"]] = podcasts.fetch(s["url"])
            except Exception as e:
                self._error(f"Podcast {s['name']}: {e}")
        want = podcasts.wanted(self.settings, subs, feeds)
        sync_on = bool((self.settings.get("podcasts") or {}).get("sync"))
        folder_feed = {podcasts.channel_folder(s["name"]) + "/": s["url"] for s in subs if podcasts.channel_folder(s["name"])}

        def feed_read(path):   # unsubscribed (no feed) counts as read
            url = next((u for f, u in folder_feed.items() if path.startswith(f)), None)
            return url is None or url in feeds
        # only drop an episode when its feed was read this time: a feed that's down shouldn't empty the Y1
        drop = [path for path in mine if path not in want and (not sync_on or feed_read(path))]
        if drop:
            device.remove(drop)
            for path in drop:
                mine.pop(path, None)
        have = podcasts.downloaded()
        todo = [(path, s, e) for path, (s, e) in want.items() if path not in have]
        covers = {s["name"]: feeds[s["url"]]["image"] for _, s, _ in todo if feeds[s["url"]]["image"]}
        with tempfile.TemporaryDirectory(prefix="innisync-pod-") as work:
            for name, url in covers.items():
                cover = f"{podcasts.channel_folder(name)}/cover.jpg"
                if not device.exists(cover):
                    try:
                        local = os.path.join(work, "cover.jpg")
                        urllib.request.urlretrieve(url, local)
                        device.mkdirs([os.path.dirname(cover)])
                        device.push(local, cover)
                    except Exception:
                        pass   # art is nice to have; the Y1 fetches it itself when it's online
            for n, (path, s, e) in enumerate(todo, 1):
                if self.cancel:
                    return
                self._set(message=f"Copying podcast episodes {n} of {len(todo)}", current=f"{s['name']}: {e['title'].strip()}")
                try:
                    local = os.path.join(work, "ep.mp3")
                    podcasts.download(e, local)
                    device.mkdirs([os.path.dirname(path)])
                    device.push_whole(local, path)
                    os.remove(local)
                    mine[path] = e["url"]
                except Exception as ex:
                    self._error(f"Podcast {e['title'].strip()}: {ex}")
        # an episode the Y1 already had stays the Y1's: InniSync never claims (or deletes) it

    def _sync_lyrics(self, songs):
        """.lrc beside each synced song that has timed lyrics, from Jellyfin first, then LRCLIB. The manifest remembers
        songs already checked ("lrc": path, or "" for none; "lrclib": True once LRCLIB answered) so each song is asked
        about once; turning the option off removes them."""
        if not self.settings.get("lyrics", True):
            old = [m["lrc"] for m in songs.values() if m.get("lrc")]
            if old:
                device.remove(old)
            for m in songs.values():
                m.pop("lrc", None)
                m.pop("lrclib", None)
            return
        use_lrclib = self.settings.get("lyrics_lrclib", True)
        todo = [i for i, m in songs.items() if i in self.lib and
                (("lrc" not in m and self.lib[i].get("lyrics")) or (use_lrclib and not m.get("lrc") and not m.get("lrclib")))]
        if not todo:
            return
        server = self.settings.get("lrclib_url") or lyrics.DEFAULT_SERVER
        lrclib_down = False
        with tempfile.TemporaryDirectory(prefix="innisync-lrc-") as work:
            for n, i in enumerate(todo, 1):
                if self.cancel:
                    return
                m, song = songs[i], self.lib[i]
                self._set(message=f"Finding lyrics {n} of {len(todo)}", current=song["name"])
                try:
                    text = self.jf.lrc(i) if "lrc" not in m and song.get("lyrics") else None
                    if not text and use_lrclib and not lrclib_down:
                        try:
                            text = lyrics.synced(song, server)
                            m["lrclib"] = True
                        except lyrics.Unavailable as e:
                            lrclib_down = True   # stop asking this sync; these songs are tried again next time
                            self._error(f"Lyrics: {e}")
                    if text:
                        local, remote = os.path.join(work, "l.lrc"), os.path.splitext(m["path"])[0] + ".lrc"
                        with open(local, "w", encoding="utf-8") as f:
                            f.write(text)
                        device.push(local, remote)
                        m["lrc"] = remote
                    else:
                        m["lrc"] = m.get("lrc") or ""
                except Exception as e:
                    self._error(f"Lyrics for {song['name']}: {e}")

    def _write_autoplay(self, man):
        """Sound-alike matches for InniClassic Autoplay, as /storage/sdcard0/.innisync_autoplay.json:
        {"version": 2, "paths": [song path, ...], "next": [[indexes of its closest songs], ...]} (paths listed once,
        so ~100 KB for 700 songs instead of over 1 MB)."""
        if not self.autoplay:
            return
        songs = man["songs"]
        try:
            matches = self.autoplay(list(songs))
        except Exception as e:  # a bonus like the mixes: never fail the sync over it
            self._error(f"Autoplay matches: {e}")
            return
        ids = [i for i in songs if i in matches]
        pos = {i: n for n, i in enumerate(ids)}
        body = {"version": 2, "paths": [songs[i]["path"] for i in ids],
                "next": [[pos[j] for j in matches[i] if j in pos][:15] for i in ids]}
        with tempfile.TemporaryDirectory(prefix="innisync-gen-") as work:
            local = os.path.join(work, "autoplay.json")
            with open(local, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, separators=(",", ":"))
            device.push(local, AUTOPLAY_MAP + ".tmp")
            device.shell(f"mv {device.q(AUTOPLAY_MAP + '.tmp')} {device.q(AUTOPLAY_MAP)}")

    def _write_playlists(self, playlists, man):
        songs = man["songs"]
        lists = [(pl["name"], self.playlist_items.get(pl["id"], [])) for pl in playlists]
        if self.soundalike:
            try:
                lists += [(("Mix - " if g.get("kind") == "mix" else "Similar - ") + g["name"], g["items"]) for g in self.soundalike(list(songs))]
            except Exception as e:  # a bonus; never fail the sync over it
                self._error(f"Mixes: {e}")
        written = []
        with tempfile.TemporaryDirectory(prefix="innisync-pl-") as work:
            for title, items in lists:
                lines = [songs[i]["path"] for i in items if i in songs]
                if not lines:
                    continue
                base, n = PLAYLIST_PREFIX + fat_safe(title, 60), 1
                name = base + ".m3u8"
                while name.casefold() in {w.casefold() for w in written}:   # the card ignores case: "Rock" is "rock"
                    n += 1
                    name = f"{base} ({n}).m3u8"
                local = os.path.join(work, "pl.m3u8")
                with open(local, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n" + "\n".join(lines) + "\n")
                device.push(local, f"{PLAYLIST_DIR}/{name}")
                written.append(name)
        kept = {w.casefold() for w in written}
        stale = [n for n in man.get("playlists", []) if n.casefold() not in kept]   # a renamed-by-case list is the same file
        if stale:
            device.remove([f"{PLAYLIST_DIR}/{n}" for n in stale])
        man["playlists"] = written
