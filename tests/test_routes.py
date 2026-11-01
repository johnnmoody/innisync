"""The API routes: every path the interface calls exists, and what a route declares it needs (a connected Y1, the
USB cable, no other job running) stops it before it runs."""
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.request

import pytest

from innisync import device, routes, server, state

UI = os.path.join(os.path.dirname(__file__), "..", "ui", "src")


def test_every_api_path_the_interface_calls_is_a_route():
    called = set()
    for folder, _, files in os.walk(UI):
        for f in files:
            if f.endswith((".svelte", ".js")):
                called |= set(re.findall(r"""["'`](/api/[a-zA-Z0-9/_-]+)""", open(os.path.join(folder, f)).read()))
    assert called, "found no API calls in the interface"
    missing = sorted(p for p in called if not routes.find("GET", p) and not routes.find("POST", p))
    assert missing == []


@pytest.fixture
def url(monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = server.serve(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield lambda p: f"http://127.0.0.1:{port}{p}"
    httpd.shutdown()


def post(u, body=None):
    req = urllib.request.Request(u, method="POST", data=json.dumps(body or {}).encode(),
                                 headers={"X-InniSync": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def y1(monkeypatch, **kw):
    info = {"connected": True, "serial": "S", "name": "Y1", "transport": "usb", **kw}
    monkeypatch.setattr(state.S, "device_info", lambda force=False: info)


def test_routes_that_need_a_y1_say_so(url, monkeypatch):
    y1(monkeypatch, connected=False)
    for p in ("/api/device/sync", "/api/device/rename", "/api/device/backup", "/api/device/podcasts/subscribe"):
        assert post(url(p)) == (409, {"error": "The Y1 isn't connected"}), p


def test_file_moves_need_the_cable(url, monkeypatch):
    y1(monkeypatch, transport="wifi")
    code, body = post(url("/api/device/backup"))
    assert code == 409 and "USB" in body["error"]
    monkeypatch.setattr(state.S, "busy", lambda: "A sync is already running")
    code, body = post(url("/api/update/install"), {"dryRun": True})   # a dry run moves nothing: only "busy" stops it
    assert (code, body["error"]) == (409, "A sync is already running")


def test_one_long_job_at_a_time(url, monkeypatch):
    y1(monkeypatch)
    monkeypatch.setattr(state.S, "busy", lambda: "The Y1 is being backed up. Try again in a minute.")
    ran = []
    monkeypatch.setattr(device, "write_manifest", lambda man: ran.append(man))
    assert post(url("/api/device/manifest/rebuild"))[0] == 409 and ran == []


def test_unknown_paths(url):
    assert post(url("/api/nothing"))[0] == 404
