"""The sync record (manifest) on the Y1: read strictly, written safely, rebuilt from the files when it's damaged."""
import json

import pytest

from fakes import FakeY1, song
from innisync import device, sync

M = device.MANIFEST


def test_no_record_means_a_fresh_y1(monkeypatch):
    FakeY1().install(monkeypatch)
    assert device.read_manifest() == {"songs": {}, "playlists": []}


def test_unreadable_record_stops_instead_of_pretending_the_y1_is_empty(monkeypatch):
    y1 = FakeY1({M: b'{"songs": {"a": {"path": "/x.mp3"}}}'}).install(monkeypatch)
    y1.fail_cat = True
    with pytest.raises(device.ManifestError):
        device.read_manifest()


@pytest.mark.parametrize("body", [b'{"songs": {"a"', b"[]", b'{"playlists": []}', b'{"songs": []}'])
def test_damaged_record_stops(monkeypatch, body):
    FakeY1({M: body}).install(monkeypatch)
    with pytest.raises(device.ManifestError):
        device.read_manifest()


def test_record_is_written_beside_and_renamed_into_place(monkeypatch):
    y1 = FakeY1().install(monkeypatch)
    device.write_manifest({"songs": {"a": {"path": "/p.mp3", "size": 3}}, "playlists": []})
    assert y1.pushed == [M + ".tmp"]           # never written straight over the real one
    assert M + ".tmp" not in y1.files
    assert device.read_manifest()["songs"]["a"]["path"] == "/p.mp3"


def test_sync_job_reports_a_damaged_record_and_changes_nothing(monkeypatch):
    y1 = FakeY1({M: b"not json"}).install(monkeypatch)
    monkeypatch.setattr(device, "info", lambda: {"connected": True, "serial": "S", "name": "Y1", "transport": "usb", "free": 10**12})
    job = sync.SyncJob(None, {}, {**sync.DEFAULT_SETTINGS, "play_counts": False}, {}, [])
    job._run()
    assert job.status["state"] == "error" and job.status["code"] == "manifest"
    assert y1.pushed == []


def test_rebuild_finds_songs_where_sync_puts_them_ignoring_case(monkeypatch):
    a = song("a", "Poker Face", "Lady Gaga", "The Fame", track=4)
    b = song("b", "Hello", "Adele", "25", container="flac", track=1)
    c = song("c", "Not On Y1", "Nobody", "Nothing")
    lib = {s["id"]: s for s in (a, b, c)}
    path_a = sync.device_path(a, False).replace("Lady Gaga", "Lady GaGa")   # folder made earlier with other case
    path_b = sync.device_path(b, True)                                        # converted to MP3 at the time
    files = {path_a: b"x" * 10, path_a[:-4] + ".lrc": b"[00:01.00] hi", path_b: b"y" * 20,
             f"{device.SYNC_DIR}/Stray/file.mp3": b"z",
             f"{device.PLAYLIST_DIR}/{sync.PLAYLIST_PREFIX}Mine.m3u8": b"#EXTM3U\n",
             f"{device.PLAYLIST_DIR}/Someone Else.m3u8": b"#EXTM3U\n"}
    FakeY1(files).install(monkeypatch)
    man, leftover = sync.rebuild_manifest(lib)
    assert set(man["songs"]) == {"a", "b"}
    assert man["songs"]["a"]["path"] == sync.device_path(a, False)   # recorded the way sync names it
    assert man["songs"]["a"]["lrc"].endswith(".lrc") and man["songs"]["a"]["size"] == 10
    assert man["songs"]["b"]["path"].endswith(".mp3")
    assert man["playlists"] == [f"{sync.PLAYLIST_PREFIX}Mine.m3u8"]   # never claims playlists InniSync didn't write
    assert man["podcasts"] == {} and leftover == 1


def test_plan_adds_removes_and_checks_space():
    a, b, c = song("a", "A", "X", "Al"), song("b", "B", "X", "Al", track=2), song("c", "C", "Y", "Bl")
    lib = {s["id"]: s for s in (a, b, c)}
    have = {"songs": {"a": {"path": sync.device_path(a, False), "size": 5_000_000},
                      "c": {"path": sync.device_path(c, False), "size": 5_000_000}}}
    settings = {**sync.DEFAULT_SETTINGS, "mode": "selected", "artists": ["X"]}
    p = sync.plan(lib, settings, {}, [], {"free": 10**12, "serial": "S"}, have)
    assert p["adds"] == ["b"] and p["removes"] == ["c"] and p["fits"]
    tight = sync.plan(lib, settings, {}, [], {"free": 0, "serial": "S"}, have)
    assert not tight["fits"]


def test_convert_changes_the_path_so_the_song_is_replaced_not_removed():
    f = song("f", "Song", "Band", "Record", container="flac")
    assert sync.device_path(f, False).endswith(".flac") and sync.device_path(f, True).endswith(".mp3")
    lib = {"f": f}
    have = {"songs": {"f": {"path": sync.device_path(f, False), "size": 1}}}
    p = sync.plan(lib, {**sync.DEFAULT_SETTINGS, "mode": "all", "convert": True}, {}, [], {"free": 10**12}, have)
    assert p["adds"] == ["f"] and p["replaces"] == ["f"] and p["removes"] == []


def test_saved_settings_keep_only_known_keys():
    s = sync.save_settings("T", {**sync.DEFAULT_SETTINGS, "mode": "all", "junk": 1})
    assert "junk" not in s and json.load(open(sync.settings_path("T")))["mode"] == "all"
