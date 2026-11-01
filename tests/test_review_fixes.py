"""Fixes from the October 2026 code review: nothing on the Y1 is deleted before its replacement is safely there,
no two songs share a file, a sync that would empty the Y1 waits for a yes, podcast names can't reach outside their
folder, and the rest."""
import datetime
import io
import json
import socket
import threading

import pytest

from fakes import FakeY1, song
from innisync import device, playcounts, podcasts, server, subsonic, sync

M = device.MANIFEST
CONNECTED = {"connected": True, "serial": "S", "name": "Y1", "transport": "usb", "free": 10**12}


class FakeLibrary:
    """A music server that hands out each song's bytes, and can be told to fail some downloads."""
    def __init__(self, fail=()):
        self.fail = set(fail)

    def open_download(self, i):
        if i in self.fail:
            raise OSError("server went away")
        return io.BytesIO(f"audio of {i}".encode())


def run_sync(monkeypatch, lib, have, settings=None, fail=(), allow_removals=False, files=None):
    y1 = FakeY1({**(files or {}), M: json.dumps({"songs": have, "playlists": []}).encode()}).install(monkeypatch)
    for p in [m["path"] for m in have.values()]:
        y1.files.setdefault(p, b"old")
    monkeypatch.setattr(device, "info", lambda: CONNECTED)
    s = {**sync.DEFAULT_SETTINGS, "mode": "all", "play_counts": False, "lyrics": False, **(settings or {})}
    job = sync.SyncJob(FakeLibrary(fail), lib, s, {}, [], allow_removals=allow_removals)
    job._run()
    return y1, job, json.loads(y1.files[M])


# ---------- copy first, delete after ----------
def test_a_failed_copy_keeps_the_old_file_and_says_so(monkeypatch):
    f = song("f", "Song", "Band", "Record", container="flac")
    old = sync.device_path(f, False)
    y1, job, man = run_sync(monkeypatch, {"f": f}, {"f": {"path": old, "size": 3}}, {"convert": True}, fail={"f"})
    assert old in y1.files and man["songs"]["f"]["path"] == old
    assert job.status["state"] == "done" and "1 problem" in job.status["message"] and job.status["errors"]


def test_a_converted_song_is_copied_then_the_old_file_removed(monkeypatch):
    f = song("f", "Song", "Band", "Record", container="flac")
    old, new = sync.device_path(f, False), sync.device_path(f, True)
    monkeypatch.setattr(sync.SyncJob, "_fetch", lambda self, s, ext, work: _write(work, "x." + ext))
    y1, job, man = run_sync(monkeypatch, {"f": f}, {"f": {"path": old, "size": 3}}, {"convert": True})
    assert new in y1.files and old not in y1.files and man["songs"]["f"]["path"] == new
    assert y1.pushed[0] == new + ".part" and old in y1.removed   # copied (under a temporary name) first, then deleted


def _write(work, name):
    import os
    p = os.path.join(work, name)
    open(p, "wb").write(b"converted")
    return p


def test_a_file_that_wont_delete_stops_the_record_from_forgetting_it(monkeypatch):
    a = song("a", "Gone", "Band", "Record")
    path = sync.device_path(a, False)
    y1 = FakeY1({M: json.dumps({"songs": {"a": {"path": path, "size": 3}}, "playlists": []}).encode(), path: b"x"})
    y1.install(monkeypatch)
    y1.fail_on = path
    monkeypatch.setattr(device, "info", lambda: CONNECTED)
    job = sync.SyncJob(FakeLibrary(), {"a": a}, {**sync.DEFAULT_SETTINGS, "mode": "selected", "artists": [], "play_counts": False}, {}, [])
    job._run()
    assert job.status["state"] == "error" and path in y1.files


# ---------- a sync that would empty the Y1 ----------
def test_a_sync_that_takes_most_songs_off_waits_for_a_yes(monkeypatch):
    lib = {str(n): song(str(n), f"S{n}", "Band", "Record", track=n) for n in range(40)}
    have = {i: {"path": sync.device_path(s, False), "size": 5} for i, s in lib.items()}
    gone = {"0": lib["0"]}   # the server came back with one song
    y1, job, man = run_sync(monkeypatch, gone, have)
    assert job.status["code"] == "removals" and job.status["removing"] == 39 and y1.removed == []
    y1, job, man = run_sync(monkeypatch, gone, have, allow_removals=True)
    assert job.status["state"] == "done" and len(man["songs"]) == 1


def test_small_removals_need_no_confirmation():
    assert not sync.big_removal(10, 12) and not sync.big_removal(30, 100) and sync.big_removal(60, 100)


# ---------- no two songs in one file ----------
def test_songs_that_would_share_a_file_get_their_own():
    a, b = song("a", "Intro", "Band", "", track=None), song("b", "intro", "BAND", "", track=None)
    lib = {"a": a, "b": b}
    paths = sync.resolve_paths(["a", "b"], lib, False, {})
    assert paths["a"].casefold() != paths["b"].casefold()
    # once on the Y1, each keeps its name even when the other goes away
    have = {i: {"path": p} for i, p in paths.items()}
    assert sync.resolve_paths(["b"], lib, False, have)["b"] == paths["b"]


def test_fill_free_space_leaves_no_duplicate_files():
    f = song("f", "Song", "Band", "Record", container="flac")
    others = {str(n): song(str(n), f"O{n}", "Other", "Rec", track=n) for n in range(5)}
    lib = {"f": f, **others}
    have = {"f": {"path": sync.device_path(f, False), "size": 3}}
    s = {**sync.DEFAULT_SETTINGS, "mode": "selected", "artists": ["Band"], "convert": True, "fill_free": True}
    p = sync.plan(lib, s, {}, [], {"free": 10**12, "serial": "S"}, {"songs": have})
    assert "f" in p["replaces"] and "f" in p["adds"] and len(p["adds"]) == 6   # the fill songs were added too


# ---------- playlists ----------
def test_playlist_renamed_by_case_is_not_deleted(monkeypatch):
    a = song("a", "A", "X", "Al")
    path = sync.device_path(a, False)
    y1 = FakeY1().install(monkeypatch)
    job = sync.SyncJob(None, {"a": a}, sync.DEFAULT_SETTINGS, {"p1": ["a"], "p2": ["a"]}, [])
    man = {"songs": {"a": {"path": path}}, "playlists": [f"{sync.PLAYLIST_PREFIX}rock.m3u8"]}
    job._write_playlists([{"id": "p1", "name": "Rock"}, {"id": "p2", "name": "ROCK"}], man)
    assert man["playlists"] == [f"{sync.PLAYLIST_PREFIX}Rock.m3u8", f"{sync.PLAYLIST_PREFIX}ROCK (2).m3u8"]
    assert y1.removed == []


# ---------- podcasts ----------
@pytest.mark.parametrize("name", ["..", ".", "", "   ", "a\nb"])
def test_a_podcast_name_never_points_outside_its_folder(name):
    assert podcasts.channel_folder(name) is None and podcasts.episode_path(name, "Ep") is None
    assert podcasts.channel_folder(podcasts.channel_name(name)) is not None


def test_unsubscribing_a_badly_named_podcast_deletes_nothing(monkeypatch):
    y1 = FakeY1({podcasts.SUBS: b"..|http://x/feed\n", f"{device.SD}/Music/keep.mp3": b"x"}).install(monkeypatch)
    podcasts.unsubscribe("http://x/feed", remove_episodes=True)
    assert f"{device.SD}/Music/keep.mp3" in y1.files and y1.removed == []


# ---------- the Y1's shell ----------
def test_shell_ok_raises_when_the_y1_command_fails(monkeypatch):
    FakeY1({"/a": b"1"}).install(monkeypatch)
    device.shell_ok("mv /a /b")
    with pytest.raises(device.DeviceError):
        device.shell_ok("mv /a /c")   # /a is gone now


# ---------- play counts ----------
class FlakyServer:
    def __init__(self, fail_at):
        self.fail_at, self.marked = fail_at, []

    def last_played(self, i):
        return None

    def mark_played(self, i, when):
        if len(self.marked) == self.fail_at:
            raise OSError("server went away")
        self.marked.append(i)


def test_play_counts_sent_before_a_failure_are_not_sent_again():
    lib = {str(n): song(str(n), f"T{n}", "A", "B") for n in range(5)}
    log = "#AUDIOSCROBBLER/1.1\n" + "".join(f"A\tB\tT{n}\t\t100\tL\t{1792774392 + n}\t\n" for n in range(5))
    with pytest.raises(OSError):
        playcounts.send(FlakyServer(fail_at=3), lib, "FLAKY", log)
    srv = FlakyServer(fail_at=99)
    playcounts.send(srv, lib, "FLAKY", log)
    assert srv.marked == ["3", "4"]


def test_unmatched_plays_are_tried_again_when_the_song_appears():
    log = "#AUDIOSCROBBLER/1.1\nA\tB\tLater\t\t100\tL\t1792774392\t\n"
    srv = FlakyServer(fail_at=99)
    assert playcounts.send(srv, {}, "LATER", log) == {"new": 1, "sent": 0, "unmatched": 1}
    assert playcounts.send(srv, {"x": song("x", "Later", "A", "B")}, "LATER", log) == {"new": 0, "sent": 1, "unmatched": 0}


# ---------- dates from Subsonic servers ----------
def test_subsonic_dates_keep_their_offset():
    assert subsonic._when("2026-10-31T07:00:00.5-05:00") == datetime.datetime(2026, 10, 31, 12, 0, 0, 500000, tzinfo=datetime.timezone.utc)
    assert subsonic._iso("2026-10-31T12:00:00Z") == "2026-10-31T12:00:00Z" and subsonic._when(None) is None


# ---------- the local server's files ----------
def test_static_files_stay_inside_the_web_folder():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = server.serve(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        c = socket.create_connection(("127.0.0.1", port))
        c.sendall(f"GET /../../../../../../etc/hosts HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        reply = c.recv(200).decode()
        c.close()
        assert " 404 " in reply.split("\r\n")[0]
    finally:
        httpd.shutdown()
