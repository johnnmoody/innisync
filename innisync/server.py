"""InniSync's local server: serves the interface and its JSON API (innisync/routes) on 127.0.0.1 only."""
import json
import mimetypes
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import backup, device, routes, soundalike
from .jellyfin import NotSignedIn
from .state import S, load_prefs

WEB = os.path.join(os.path.dirname(__file__), "web")


class Handler(BaseHTTPRequestHandler):
    server_version = "InniSync/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---- who may talk to this server ----
    # Any web page you visit can send requests to 127.0.0.1, so: the Host must be this server (stops DNS rebinding),
    # API calls must carry the X-InniSync header (a page on another site can't add it without a CORS preflight, which
    # this server never answers), and a page that sends an Origin must be InniSync's own. Covers, songs and Y1
    # pictures load through <img>/<audio>, which can't send headers; they're read-only.
    PUBLIC = ("/art/", "/stream/", "/devimg")

    def _allowed(self, method, path):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return False
        if path.startswith("/api/") and self.headers.get("X-InniSync") != "1":
            return False
        return not (method == "POST" and path.startswith(self.PUBLIC))

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        u = urllib.parse.urlparse(self.path)
        if not self._allowed(method, u.path):
            return self.send_json({"error": "Not allowed"}, 403)
        hit = routes.find(method, u.path)
        if not hit:
            return self.send_static(u.path) if method == "GET" else self.send_json({"error": "not found"}, 404)
        fn, opts = hit
        try:
            req = routes.Request(self, u.path, dict(urllib.parse.parse_qsl(u.query)), opts["raw"])
            out = routes.precheck(req, opts) or fn(req)
            if out is not None:
                self.send_json(*(out if isinstance(out, tuple) else (out,)))
        except NotSignedIn as e:
            self.send_json({"error": str(e), "signIn": True}, 401)
        except device.ManifestError as e:
            self.send_json({"error": str(e), "code": "manifest"}, 409)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ---- reading requests, writing responses (used by the routes) ----
    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def read_raw(self, limit=4 << 30):
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > limit:
            raise ValueError("Nothing was uploaded" if not n else "That file is too big")
        return self.rfile.read(n)

    def send_json(self, obj, code=200):
        self.send_bytes(json.dumps(obj).encode(), "application/json", "no-store", code)

    def send_bytes(self, data, ctype, cache, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_static(self, path):
        """A file of the built interface; nothing outside its folder."""
        web = os.path.realpath(WEB)
        full = os.path.realpath(os.path.join(web, path.lstrip("/") or "index.html"))
        if os.path.commonpath([full, web]) != web or not os.path.isfile(full):
            return self.send_json({"error": "not found"}, 404)
        with open(full, "rb") as f:
            data = f.read()
        self.send_bytes(data, mimetypes.guess_type(full)[0] or "application/octet-stream", "no-cache")


def serve(port=8765):
    backup.set_folder(load_prefs()["backup_folder"])
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    soundalike.SOURCE = f"http://127.0.0.1:{port}/stream/{{}}?original=1"

    def warm():
        try:
            S.library()
            S.soundalike()  # starts analysing any of the Y1's songs not analyzed yet
        except Exception:
            pass  # signed out, or the server is down: it catches up on the next request
    threading.Thread(target=warm, daemon=True).start()
    return httpd
