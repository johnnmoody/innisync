"""iTunes-style one-way sync: Jellyfin selection -> Y1 (Music/InniSync + Y1_Playlists/*.m3u8)."""
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

from . import device, lyrics, playcounts, podcasts, tools
from .device import PLAYABLE, PLAYLIST_DIR, SD, SYNC_DIR

APP_DIR = os.path.expanduser("~/Library/Application Support/InniSync")
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
        return {**DEFAULT_SETTINGS, **json.load(open(settings_path(serial)))}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def known_serials():
    """Every Y1 InniSync has sync settings for."""
    import glob
    return [os.path.basename(f)[7:-5] for f in glob.glob(os.path.join(APP_DIR, "device_*.json"))]


def save_settings(serial, s):
    clean = {k: s.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    json.dump(clean, open(settings_path(serial), "w"), indent=1)
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


def plan(lib, settings, playlist_items, playlists, dev_info, manifest):
    want = selected_songs(lib, settings, playlist_items)
    conv = settings["convert"]
    have = manifest.get("songs", {})
    want_paths = {i: device_path(lib[i], conv) for i in want}
    adds = [i for i in want if have.get(i, {}).get("path") != want_paths[i]]
    removes = [i for i in have if i not in want_paths or have[i].get("path") != want_paths.get(i)]
    add_bytes = sum(est_size(lib[i], conv) for i in adds)
    remove_bytes = sum(have[i].get("size", 0) for i in removes)
    budget = dev_info.get("free", 0) - RESERVE + remove_bytes
    fill = []
    if settings["fill_free"] and settings["sync_music"] and settings["mode"] == "selected":
        room = budget - add_bytes
        pool = [i for i in lib if i not in want_paths]
        random.Random(dev_info.get("serial", "y1")).shuffle(pool)
        for i in pool:
            sz = est_size(lib[i], conv)
            if sz <= room:
                fill.append(i)
                room -= sz
            if room < 50 << 20:
                break
        for i in fill:
            want_paths[i] = device_path(lib[i], conv)
        adds += [i for i in fill if have.get(i, {}).get("path") != want_paths[i]]
        removes = [i for i in removes if i not in want_paths]
        add_bytes = sum(est_size(lib[i], conv) for i in adds)
    sel_pl = [p for p in playlists if p["id"] in settings["playlists"]] if settings["sync_music"] else []
    if settings["sync_music"] and settings["mode"] == "all":
        sel_pl = playlists
    return {
        "want": want_paths,
        "adds": adds,
        "removes": removes,
        "add_bytes": add_bytes,
        "remove_bytes": remove_bytes,
        "fits": add_bytes <= budget,
        "budget": budget,
        "playlists": sel_pl,
        "songs_after": len(want_paths),
        "bytes_after": dev_info.get("synced", 0) + add_bytes - remove_bytes,
    }


class SyncJob:
    """Runs one sync in a background thread; .status is polled by the UI."""

    def __init__(self, jf, lib, settings, playlist_items, playlists, soundalike=None, autoplay=None):
        self.jf, self.lib, self.settings = jf, lib, settings
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
        self.status.update(kw)

    def _send_play_counts(self, serial):
        try:
            r = playcounts.send(self.jf, self.lib, serial, playcounts.read_log(),
                                progress=lambda n, total: self._set(message=f"Updating play counts ({n} of {total})"),
                                cancel=lambda: self.cancel)
            self._set(plays=r)
        except Exception as e:
            self.status["errors"].append(f"Play counts: {e}")

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
            conv = self.settings["convert"]
            adds = p["adds"]
            total = len(p["removes"]) + len(adds)
            self._set(total=total, state="syncing")
            songs = man.setdefault("songs", {})

            if p["removes"]:
                self._set(message="Removing songs")
                device.remove([f for i in p["removes"] for f in (songs.get(i, {}).get("path"), songs.get(i, {}).get("lrc")) if f])
                for i in p["removes"]:
                    songs.pop(i, None)
                self.status["done"] += len(p["removes"])
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
                        device.push(local, p["want"][i])
                        songs[i] = {"path": p["want"][i], "size": os.path.getsize(local)}
                        for f in os.listdir(work):
                            os.unlink(os.path.join(work, f))
                    except Exception as e:  # keep going; report at the end
                        self.status["errors"].append(f"{s['artist']} - {s['name']}: {e}")
                    self.status["done"] += 1
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
            self._set(state="cancelled" if self.cancel else "done",
                      message="Sync cancelled" if self.cancel else "Y1 sync is complete. OK to disconnect.")
        except Exception as e:
            self._set(state="error", message=str(e))

    def _sync_podcasts(self, man):
        """Copy the episodes the Podcasts settings pick into InniClassic's Podcasts folders; remove ones InniSync copied
        that aren't picked any more. Episodes the Y1 downloaded itself are left alone."""
        mine = man.setdefault("podcasts", {})   # device path -> episode url, for files InniSync copied
        try:
            subs = podcasts.subscriptions()
        except Exception as e:
            self.status["errors"].append(f"Podcasts: {e}")
            return
        feeds = {}
        for s in subs if (self.settings.get("podcasts") or {}).get("sync") else []:
            self._set(message="Checking podcasts", current=s["name"])
            try:
                feeds[s["url"]] = podcasts.fetch(s["url"])
            except Exception as e:
                self.status["errors"].append(f"Podcast {s['name']}: {e}")
        want = podcasts.wanted(self.settings, subs, feeds)
        sync_on = bool((self.settings.get("podcasts") or {}).get("sync"))
        folder_feed = {f"{podcasts.ROOT}/{podcasts.safe(s['name'])}/": s["url"] for s in subs}

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
                cover = f"{podcasts.ROOT}/{podcasts.safe(name)}/cover.jpg"
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
                    device.push(local, path)
                    os.remove(local)
                    mine[path] = e["url"]
                except Exception as ex:
                    self.status["errors"].append(f"Podcast {e['title'].strip()}: {ex}")
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
                            self.status["errors"].append(f"Lyrics: {e}")
                    if text:
                        local, remote = os.path.join(work, "l.lrc"), os.path.splitext(m["path"])[0] + ".lrc"
                        open(local, "w", encoding="utf-8").write(text)
                        device.push(local, remote)
                        m["lrc"] = remote
                    else:
                        m["lrc"] = m.get("lrc") or ""
                except Exception as e:
                    self.status["errors"].append(f"Lyrics for {song['name']}: {e}")

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
            self.status["errors"].append(f"Autoplay matches: {e}")
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
                self.status["errors"].append(f"Mixes: {e}")
        written = []
        with tempfile.TemporaryDirectory(prefix="innisync-pl-") as work:
            for title, items in lists:
                lines = [songs[i]["path"] for i in items if i in songs]
                if not lines:
                    continue
                name = PLAYLIST_PREFIX + fat_safe(title, 60) + ".m3u8"
                local = os.path.join(work, "pl.m3u8")
                with open(local, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n" + "\n".join(lines) + "\n")
                device.push(local, f"{PLAYLIST_DIR}/{name}")
                written.append(name)
        stale = [n for n in man.get("playlists", []) if n not in written]
        if stale:
            device.remove([f"{PLAYLIST_DIR}/{n}" for n in stale])
        man["playlists"] = written
