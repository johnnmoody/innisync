"""Start the built app (dist/) with --server-only and check it serves the interface and answers the API with its
version: proves the bundle's Python and packages load on this system. Used by the release build."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
EXE = {"darwin": os.path.join(DIST, "InniSync.app", "Contents", "MacOS", "InniSync"),
       "win32": os.path.join(DIST, "InniSync", "InniSync.exe")}.get(sys.platform, os.path.join(DIST, "InniSync", "InniSync"))
PORT = 8799


def get(path):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers={"X-InniSync": "1"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read()


def main():
    env = {**os.environ, "INNISYNC_PORT": str(PORT), "INNISYNC_DATA": tempfile.mkdtemp(prefix="innisync-smoke-")}
    proc = subprocess.Popen([EXE, "--server-only"], env=env)
    try:
        for _ in range(120):
            try:
                page = get("/")
                break
            except OSError:
                if proc.poll() is not None:
                    sys.exit(f"InniSync exited with {proc.returncode} before it served anything")
                time.sleep(0.5)
        else:
            sys.exit("InniSync didn't answer within a minute")
        assert b"<html" in page.lower(), "the interface didn't come back"
        prefs = json.loads(get("/api/prefs"))
        print(f"InniSync {prefs['version']} on {prefs['platform']}: serves the interface and the API")
    finally:
        proc.terminate()
        proc.wait(20)


if __name__ == "__main__":
    main()
