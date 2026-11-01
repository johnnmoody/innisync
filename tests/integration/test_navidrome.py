"""InniSync against a real Navidrome (Subsonic) server with three generated songs: library, playlists, play counts,
streaming, downloads, covers, and the InniSync server on top. Skipped unless Navidrome and ffmpeg are installed
(INNISYNC_NAVIDROME=/path/to/navidrome, or `navidrome` on PATH)."""
import datetime
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

import pytest

from innisync import server, state, subsonic

ND = os.environ.get("INNISYNC_NAVIDROME") or shutil.which("navidrome") or os.path.expanduser("~/Library/Caches/innisync-test/nd/navidrome")
FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not (os.path.exists(ND) and FFMPEG), reason="needs Navidrome and ffmpeg")
SONGS = [("Alpha", "Test Band", "First Record", 1), ("Beta", "Test Band", "First Record", 2), ("Gamma", "Other Band", "Second Record", 1)]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def navidrome():
    root = tempfile.mkdtemp(prefix="innisync-nd-")
    music, data = os.path.join(root, "music"), os.path.join(root, "data")
    os.makedirs(music)
    os.makedirs(data)
    for i, (title, artist, album, track) in enumerate(SONGS):
        subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={440 + 110 * i}:duration=4",
                        "-metadata", f"title={title}", "-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}",
                        "-metadata", f"album={album}", "-metadata", f"track={track}", "-metadata", "genre=Test",
                        "-b:a", "128k", os.path.join(music, f"{title}.mp3")], check=True)
    port = free_port()
    env = {**os.environ, "ND_MUSICFOLDER": music, "ND_DATAFOLDER": data, "ND_PORT": str(port), "ND_ADDRESS": "127.0.0.1",
           "ND_LOGLEVEL": "error", "ND_ENABLEINSIGHTSCOLLECTOR": "false", "ND_SCANNER_SCHEDULE": "0"}
    proc = subprocess.Popen([ND], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/ping", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        user, password = "admin", secrets.token_hex(8)   # a throwaway account on this throwaway server
        req = urllib.request.Request(base + "/auth/createAdmin", data=json.dumps({"username": user, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        for _ in range(60):   # wait for the first scan
            if len(subsonic._call(base, user, password, "search3", query="", songCount=10).get("searchResult3", {}).get("song", [])) == 3:
                break
            time.sleep(0.5)
        yield {"base": base, "user": user, "password": password, "music": music}
    finally:
        proc.terminate()
        proc.wait(10)
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def client(navidrome, monkeypatch):
    monkeypatch.setattr(subsonic, "_keychain", lambda action, account, secret=None: navidrome["password"] if action == "get" else None)
    monkeypatch.setattr(subsonic, "load_config", lambda: {"server": navidrome["base"], "user_name": navidrome["user"]})
    return subsonic.Subsonic()


def test_library(client):
    songs = {s["name"]: s for s in client.songs()}
    assert set(songs) == {"Alpha", "Beta", "Gamma"}
    a = songs["Alpha"]
    assert (a["artist"], a["album"], a["track"], a["container"]) == ("Test Band", "First Record", 1, "mp3")
    assert a["duration"] >= 3 and a["size"] > 0 and a["genres"] == ["Test"]


def test_playlists_are_created_in_order(client):
    ids = [s["id"] for s in sorted(client.songs(), key=lambda s: s["name"], reverse=True)]
    client.create_playlist("InniSync test", ids)
    pl = next(p for p in client.playlists() if p["name"] == "InniSync test")
    assert client.playlist_items(pl["id"]) == ids


def test_play_counts_and_last_played(client):
    s = next(x for x in client.songs() if x["name"] == "Beta")
    when = datetime.datetime(2026, 10, 31, 12, 0, 0, tzinfo=datetime.timezone.utc)
    client.mark_played(s["id"], when)
    after = next(x for x in client.songs() if x["name"] == "Beta")
    assert after["plays"] == s["plays"] + 1
    assert abs((client.last_played(s["id"]) - when).total_seconds()) < 2


def test_streaming_downloads_and_covers(client, navidrome):
    s = next(x for x in client.songs() if x["name"] == "Gamma")
    with urllib.request.urlopen(client.stream_request(s["id"], s["container"], "bytes=0-99"), timeout=10) as r:
        assert r.status == 206 and len(r.read()) == 100
    with client.open_download(s["id"]) as r:
        assert len(r.read()) == os.path.getsize(os.path.join(navidrome["music"], "Gamma.mp3"))
    with urllib.request.urlopen(client.image_request(s["albumId"], 100), timeout=10) as r:
        assert r.status == 200 and r.headers.get("Content-Type", "").startswith("image/")
    assert client.lrc(s["id"]) is None


def test_innisync_server_on_subsonic(client, monkeypatch):
    monkeypatch.setattr(state, "load_prefs", lambda: {**state.DEFAULT_PREFS, "backend": "subsonic"})
    state.S.reset()
    port = free_port()
    httpd = server.serve(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        get = lambda p: json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{p}", headers={"X-InniSync": "1"}), timeout=30))
        lib = get("/api/library")
        assert len(lib["songs"]) == 3 and any(p["name"] == "InniSync test" for p in lib["playlists"])
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/smart/preview", method="POST", headers={"X-InniSync": "1", "Content-Type": "application/json"},
                                     data=json.dumps({"name": "x", "rules": [{"field": "artist", "op": "is", "value": "test band"}]}).encode())
        assert json.load(urllib.request.urlopen(req, timeout=30))["count"] == 2
    finally:
        httpd.shutdown()
        state.S.reset()
