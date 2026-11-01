"""Menu-bar item: the Y1's state at a glance (connected, battery, sync progress), Sync Now / Back Up Now, and a
notification when a sync or update finishes or a new InniClassic is out.

The window process already runs Cocoa (pywebview), so this is a plain NSStatusItem in the same app. State comes from
the local InniSync API on a background thread; only menu updates run on the main thread.
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

import objc
from AppKit import NSApplication, NSImage, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
from Foundation import NSObject
from PyObjCTools import AppHelper

ICON = os.path.join(os.path.dirname(__file__), "web", "img", "logo_lcd.png")
POLL = 3
HEADERS = {"X-InniSync": "1"}   # the local server only answers API calls that carry it


def notify(title, text):
    """A macOS notification (through osascript: this process is the shared Python.app, so it can't register its own)."""
    script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
    subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _Controller(NSObject):
    def initWithPort_window_(self, port, window):
        self = objc.super(_Controller, self).init()
        self.base, self.window = f"http://127.0.0.1:{port}", window
        self.seen = {"sync": None, "update": None, "offered": None}
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        img = NSImage.alloc().initWithContentsOfFile_(ICON)
        if img:
            img.setSize_((18, 18))
            img.setTemplate_(True)   # follows the light/dark menu bar
            self.item.button().setImage_(img)
        else:
            self.item.button().setTitle_("InniSync")
        self.menu = NSMenu.alloc().init()
        self.state = self._add("InniSync", None, enabled=False)
        self.detail = self._add("", None, enabled=False)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.syncItem = self._add("Sync Y1 Now", "syncNow:")
        self.backupItem = self._add("Back Up Y1 Now", "backUpNow:")
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add("Show InniSync", "show:")
        self._add("Quit InniSync", "quit:")
        self.item.setMenu_(self.menu)
        threading.Thread(target=self._poll, daemon=True).start()
        return self

    @objc.python_method
    def _add(self, title, action, enabled=True):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            it.setTarget_(self)
        it.setEnabled_(enabled)
        self.menu.addItem_(it)
        return it

    # ---- talking to the InniSync server (background thread) ----
    @objc.python_method
    def _get(self, path):
        with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=HEADERS), timeout=20) as r:
            return json.load(r)

    @objc.python_method
    def _post(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body or {}).encode(), method="POST",
                                     headers={**HEADERS, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return json.load(e)

    @objc.python_method
    def _poll(self):
        while True:
            try:
                self._tick()
            except Exception:
                pass   # server busy or starting: try again next round
            time.sleep(POLL)

    @objc.python_method
    def _tick(self):
        dev = self._get("/api/device")
        sync = self._get("/api/sync/status")
        upd = self._get("/api/update/status")
        active = sync.get("state") in ("starting", "checking", "syncing")
        if active:
            title = f"Syncing {dev.get('name') or 'Y1'}"
            detail = f"{sync.get('done', 0)} of {sync['total']}: {sync.get('message', '')}" if sync.get("total") else sync.get("message", "")
        elif upd.get("state") in ("starting", "downloading", "verifying", "backing_up", "installing"):
            title, detail = f"Updating {dev.get('name') or 'Y1'}", upd.get("message", "")
        elif dev.get("connected"):
            title = f"{dev['name']}: connected"
            detail = f"Battery {dev['battery']}%{' (charging)' if dev.get('charging') else ''}" if dev.get("battery") is not None else ""
        else:
            title, detail = "No Y1 connected", ""
        AppHelper.callAfter(self._render, title, detail, bool(dev.get("connected")), active)
        self._notifications(dev, sync, upd)

    @objc.python_method
    def _notifications(self, dev, sync, upd):
        s = sync.get("state")
        if self.seen["sync"] in ("starting", "checking", "syncing") and s in ("done", "error", "cancelled"):
            errs = sync.get("errors") or []
            notify("InniSync", sync.get("message", "") + (f" ({len(errs)} problem{'s' if len(errs) != 1 else ''})" if errs else ""))
        self.seen["sync"] = s
        u = upd.get("state")
        if self.seen["update"] in ("downloading", "verifying", "backing_up", "installing") and u in ("done", "error"):
            notify("InniSync", upd.get("message", ""))
        self.seen["update"] = u
        if dev.get("connected"):
            chk = self._get("/api/update/check")   # cached for a day by the server
            if chk.get("update") and self.seen["offered"] != chk["latest"]:
                self.seen["offered"] = chk["latest"]
                notify("Y1 software update", f"InniClassic {chk['latest']} is available. Open InniSync and click Update.")

    # ---- main thread ----
    @objc.python_method
    def _render(self, title, detail, connected, active):
        self.state.setTitle_(title)
        self.detail.setTitle_(detail)
        self.detail.setHidden_(not detail)
        self.syncItem.setEnabled_(connected and not active)
        self.backupItem.setEnabled_(connected and not active)
        self.item.button().setToolTip_(f"InniSync: {title}")

    def syncNow_(self, sender):
        threading.Thread(target=lambda: self._post("/api/device/sync"), daemon=True).start()

    def backUpNow_(self, sender):
        def run():
            r = self._post("/api/device/backup")
            notify("InniSync", f"Y1 backed up ({r['name']})" if r.get("name") else f"Backup didn't finish: {r.get('error')}")
        threading.Thread(target=run, daemon=True).start()

    def show_(self, sender):
        self.window.show()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def quit_(self, sender):
        self.window.destroy()


_controller = None


def install(port, window):
    """Put the item in the menu bar. Call on the main thread once the app is running."""
    global _controller
    _controller = _Controller.alloc().initWithPort_window_(port, window)
