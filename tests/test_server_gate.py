"""The local server answers InniSync's own page and nothing else (other sites, DNS rebinding)."""
import socket
import threading
import urllib.error
import urllib.request

import pytest

from innisync import server


@pytest.fixture(scope="module")
def base():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = server.serve(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", port
    httpd.shutdown()


def status(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_apps_own_requests_work(base):
    url, _ = base
    assert status(url + "/api/prefs", headers={"X-InniSync": "1"}) == 200
    assert status(url + "/art/nothing?size=10") == 200          # covers load through <img>, without the header


def test_other_sites_are_refused(base):
    url, port = base
    assert status(url + "/api/prefs") == 403                                      # a page's plain fetch
    assert status(url + "/api/device/rescan", "POST", {"Content-Type": "text/plain", "Origin": "https://evil.example"}, b"{}") == 403
    assert status(url + "/api/device/rescan", "POST", {"X-InniSync": "1", "Origin": "https://evil.example"}, b"{}") == 403
    assert status(url + "/api/prefs", headers={"X-InniSync": "1", "Host": f"evil.example:{port}"}) == 403   # DNS rebinding
    assert status(url + "/art/x", "POST", {"X-InniSync": "1"}, b"{}") == 403      # read-only paths take no POSTs
