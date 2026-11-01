"""Smart playlists, play counts, podcasts and lyrics, without a Y1 or a music server."""
import datetime
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from fakes import song
from innisync import lyrics, playcounts, podcasts, smart

LIB = {s["id"]: s for s in [
    song("1", "Toxic", "Britney Spears", "In the Zone", plays=5, genres=["Pop"], year=2003, duration=200),
    song("2", "Gimme More", "Britney Spears", "Blackout", plays=0, genres=["Dance-Pop"], year=2007, duration=250),
    song("3", "Hello", "Adele", "25", plays=2, genres=["Soul"], year=2015, duration=295),
    song("4", "Untagged", "", "", plays=0, genres=[], year=None, duration=60),
]}


# ---------- smart playlists ----------
def test_smart_rules_all_and_any():
    d = smart.validate({"name": "x", "match": "all", "rules": [
        {"field": "artist", "op": "is", "value": "britney spears"}, {"field": "plays", "op": "is greater than", "value": 0}]})
    assert smart.evaluate(d, LIB) == ["1"]
    d = smart.validate({"name": "x", "match": "any", "rules": [
        {"field": "genre", "op": "contains", "value": "soul"}, {"field": "year", "op": "is in the range", "value": 2006, "value2": 2008}]})
    assert sorted(smart.evaluate(d, LIB)) == ["2", "3"]


def test_smart_negative_rule_holds_for_every_name():
    d = smart.validate({"name": "x", "rules": [{"field": "artist", "op": "does not contain", "value": "britney"}]})
    assert "1" not in smart.evaluate(d, LIB) and "3" in smart.evaluate(d, LIB)


def test_smart_random_limit_is_stable_and_sorted_untagged_last():
    d = smart.validate({"name": "x", "rules": [], "limit": {"on": True, "count": 2, "unit": "songs", "by": "random"}})
    assert smart.evaluate(d, LIB) == smart.evaluate(d, LIB) and len(smart.evaluate(d, LIB)) == 2
    by_artist = smart.validate({"name": "x", "rules": []})
    assert smart.evaluate(by_artist, LIB)[-1] == "4"


def test_smart_rejects_a_rule_that_cannot_apply():
    with pytest.raises(ValueError):
        smart.validate({"name": "x", "rules": [{"field": "year", "op": "contains", "value": "1"}]})
    with pytest.raises(ValueError):
        smart.validate({"name": "  ", "rules": []})


# ---------- play counts ----------
LOG = "#AUDIOSCROBBLER/1.1\n#TZ/UTC\n#CLIENT/x\n" + "\n".join([
    "Britney Spears\tIn the Zone\tToxic\t\t200\tL\t1792774392\t",
    "Adele\t25\tHello\t\t295\tL\t1661625177\t",                     # 2022: the Y1's clock had reset
    "Adele\t25\tHello\t\t295\tS\t1792774400\t",                     # skipped, not counted
    "Nobody\tNothing\tUnknown Song\t\t100\tL\t1792774500\t",
]) + "\n"


class FakeServer:
    def __init__(self, last=None):
        self.marked, self.last = [], last or {}

    def last_played(self, i):
        return self.last.get(i)

    def mark_played(self, i, when):
        self.marked.append((i, when))


def test_play_counts_are_sent_once_with_sensible_dates():
    newer = datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc)
    srv = FakeServer(last={"1": newer})
    r = playcounts.send(srv, LIB, "SER1", LOG)
    assert r == {"new": 3, "sent": 2, "unmatched": 1}
    when = dict(srv.marked)
    assert when["1"] == newer                         # never moves a newer last-played date backwards
    assert when["3"].year >= 2026                     # a reset-clock play is counted, dated now, not 2022
    assert playcounts.send(srv, LIB, "SER1", LOG)["new"] == 0   # the next sync sends nothing again


# ---------- podcasts ----------
def test_episode_paths_match_inniclassic_naming():
    assert podcasts.safe('A/B: "C"?') == "A_B_ _C__"
    assert podcasts.episode_path("Up First", "Ep 1: News") == f"{podcasts.ROOT}/Up First/Ep 1_ News.mp3"


def test_wanted_episodes_follow_the_settings():
    subs = [{"name": "Show", "url": "u1"}, {"name": "Other", "url": "u2"}]
    eps = [{"title": f"E{n}", "url": f"e{n}", "date": 100 - n} for n in range(5)]
    feeds = {"u1": {"episodes": eps}, "u2": {"episodes": eps}}
    s = {"podcasts": {"sync": True, "auto": True, "rule": "3 most recent", "which": "selected", "selected": ["u1"], "extra": ["e4"]}}
    want = podcasts.wanted(s, subs, feeds)
    assert sorted(e["title"] for (sub, e) in want.values() if sub["url"] == "u1") == ["E0", "E1", "E2", "E4"]
    assert all(sub["url"] == "u1" or e["url"] == "e4" for (sub, e) in want.values())
    assert podcasts.wanted({"podcasts": {**s["podcasts"], "sync": False}}, subs, feeds) == {}


# ---------- lyrics (LRCLIB) ----------
@pytest.fixture
def lrclib():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.server.seen.append(self.headers.get("Lrclib-Client"))
            if "Missing" in self.path:
                return self.send_error(404)
            if "Busy" in self.path:
                return self.send_error(503)
            body = json.dumps({"syncedLyrics": "[00:01.00] hello", "instrumental": False}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_lyrics_found_missing_and_unavailable(lrclib):
    srv, url = lrclib
    assert lyrics.synced({"name": "Hello", "artist": "Adele", "album": "25", "duration": 295}, url) == "[00:01.00] hello\n"
    assert lyrics.synced({"name": "Missing", "artist": "X"}, url) is None
    with pytest.raises(lyrics.Unavailable):
        lyrics.synced({"name": "Busy", "artist": "X"}, url)
    assert srv.seen[0] == lyrics.CLIENT
