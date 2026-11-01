"""The local server's API, one module per area. A route is a function that takes a Request and returns the JSON
reply (a dict, or (dict, status)), or None when it wrote the response itself (pictures, audio). What a route needs
before it runs is declared on it, so every route that needs it gets the same check:
  connected  a Y1 must be connected
  usb        the Y1 must be on the cable, not Wi-Fi (the message says why); a dry run is let through
  exclusive  no other long job (sync, update, backup) may be running on the Y1
  raw        the body is a file upload, read with Request.raw(), not JSON
"""
import functools

from ..state import S

_exact = {}      # (method, path) -> (route, options)
_prefixed = []   # (method, path prefix, route, options), for /art/<id> and /stream/<id>


def route(method, path, *, prefix=False, connected=False, usb=None, exclusive=False, raw=False):
    def register(fn):
        opts = {"connected": connected, "usb": usb, "exclusive": exclusive, "raw": raw}
        if prefix:
            _prefixed.append((method, path, fn, opts))
        else:
            _exact[(method, path)] = (fn, opts)
        return fn
    return register


get = functools.partial(route, "GET")
post = functools.partial(route, "POST")


def find(method, path):
    hit = _exact.get((method, path))
    if hit:
        return hit
    return next(((fn, opts) for m, p, fn, opts in _prefixed if m == method and path.startswith(p)), None)


def precheck(req, opts):
    """The reply that stops a route before it runs, or None."""
    if opts["connected"] and not req.info.get("connected"):
        return {"error": "The Y1 isn't connected"}, 409
    if opts["usb"] and req.info.get("transport") == "wifi" and not req.body.get("dryRun"):
        return {"error": opts["usb"]}, 409
    if opts["exclusive"] and S.busy():
        return {"error": S.busy()}, 409
    return None


class Request:
    def __init__(self, handler, path, qs, raw):
        self.handler, self.path, self.qs = handler, path, qs
        self.body = {} if raw else handler.read_json()
        self._info = None

    @property
    def info(self):
        """The Y1 as of this request (read once)."""
        if self._info is None:
            self._info = S.device_info()
        return self._info

    def raw(self):
        return self.handler.read_raw()


USB_FILES = "Connect the Y1 by USB to copy files to it: its Wi-Fi is too slow."
USB_MOVES = "Connect the Y1 by USB for this: its Wi-Fi is too slow to move files."

from . import library, media, software, y1  # noqa: E402,F401  (each registers its routes)
