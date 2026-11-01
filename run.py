"""Start InniSync: local server + a native window (pywebview). --server-only runs just the server; --selftest drives
the real window through every area and writes SELFTEST lines to the log, then quits."""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from innisync.server import load_prefs, serve  # noqa: E402

PORT = int(os.environ.get("INNISYNC_PORT", "8765"))
ICONS = os.path.join(HERE, "..", "icons")   # inside the app bundle: Contents/Resources/icons/<accent>.png


def _brand_app():
    """Show 'InniSync' and its icon (tinted in the accent colour) in the menu bar and Dock."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = info["CFBundleDisplayName"] = "InniSync"
        p = load_prefs()
        icon = os.path.join(ICONS, f"{'grey' if p.get('accent') == 'grey' else p.get('y1_color', 'black')}.png")
        if os.path.exists(icon):
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(icon))
    except Exception:
        pass


def main():
    httpd = serve(PORT)
    if "--server-only" in sys.argv:
        print(f"InniSync on http://127.0.0.1:{PORT}", flush=True)
        httpd.serve_forever()
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _brand_app()
    import webview
    from webview.menu import Menu, MenuAction
    win = webview.create_window("InniSync", f"http://127.0.0.1:{PORT}/", width=1200, height=780, min_size=(960, 620))
    menu = [Menu("InniSync", [MenuAction("Preferences…  ⌘,", lambda: win.evaluate_js("openPrefs()"))]),
            Menu("File", [MenuAction("New Playlist…", lambda: win.evaluate_js("newPlaylist()")),
                          MenuAction("New Smart Playlist…", lambda: win.evaluate_js("openSmart()"))]),
            Menu("View", [MenuAction("Show or Hide Column Browser  ⌘B", lambda: win.evaluate_js("toggleBrowser()"))])]
    if "--selftest" in sys.argv:
        threading.Thread(target=_selftest, args=(win,), daemon=True).start()
    webview.start(_after_start, (win,), menu=menu)


def _after_start(win):
    """Runs once the window is up (pywebview's start func, on its own thread)."""
    if load_prefs().get("show_menubar", True):
        from PyObjCTools import AppHelper
        from innisync import menubar
        AppHelper.callAfter(menubar.install, PORT, win)


def _selftest(win):
    """Drive the real WebKit window and log what each area shows."""
    js = win.evaluate_js
    say = lambda tag, v: print(f"SELFTEST-{tag}", json.dumps(v, default=str), flush=True)

    def wait(cond, secs=60):
        for _ in range(secs * 2):
            time.sleep(0.5)
            try:
                if js(cond):
                    return True
            except Exception:
                pass
        return False

    t0 = time.time()
    wait("document.querySelectorAll('.row').length > 0", 120)
    say("LIBRARY", {"seconds": round(time.time() - t0, 1), "rows_drawn": js("document.querySelectorAll('.row').length"),
                    "songs": js("__innisync.st.songs.length"), "status": js("document.querySelector('.status .mid').textContent"),
                    "font": js("getComputedStyle(document.body).fontFamily"), "accent": js("getComputedStyle(document.documentElement).getPropertyValue('--accent')")})

    js("document.querySelector('.row').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
    wait("__innisync.audio.currentTime > 1", 30)
    say("PLAY", {"title": js("document.querySelector('.display .title')?.textContent"), "paused": js("__innisync.audio.paused"),
                 "time": js("__innisync.audio.currentTime"), "ring": js("!!document.querySelector('.disc circle.done')")})
    js("window.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true}))")
    time.sleep(1)
    say("KEYS", {"space_paused": js("__innisync.audio.paused")})

    js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'b', metaKey: true, bubbles: true}))")
    wait("!!document.querySelector('.browser')", 10)
    js("document.querySelectorAll('.browser .col')[1].querySelectorAll('button')[1].click()")
    time.sleep(1)
    browser = {"shown": js("!!document.querySelector('.browser')"), "filtered_rows": js("__innisync.st.artist") and js("document.querySelectorAll('.row').length")}
    js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'b', metaKey: true, bubbles: true}))")
    time.sleep(1)
    browser["hidden_again"] = js("!document.querySelector('.browser')")
    say("BROWSER", browser)

    from innisync import menubar
    c = menubar._controller
    say("MENUBAR", {"installed": bool(c), "title": c and str(c.state.title()), "detail": c and str(c.detail.title())})

    if js("!!__innisync.st.device"):
        dev = {}
        js("document.querySelector('.devrow .item.dev').click()")
        wait("!!document.querySelector('.about')", 20)
        wait("!document.querySelector('.rows p').textContent.startsWith('Checking')", 30)
        dev["summary"] = js("document.querySelector('.about dl').innerText.replace(/\\n/g, ' | ')")
        dev["update"] = js("document.querySelector('.rows p').textContent")
        for tab, probe in (("music", ".lists label"), ("podcasts", ".pod, .list p"), ("books", ".book, .books p"),
                           ("themes", ".tcard"), ("settings", ".g select")):
            js(f"document.getElementById('tab-{tab}').click()")
            wait(f"document.querySelectorAll('{probe}').length > 0", 40)
            dev[tab] = js(f"document.querySelectorAll('{probe}').length")
        js("document.getElementById('tab-summary').click()")
        wait("!!document.querySelector('.about')", 10)
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/update/install", data=b'{"dryRun": true}', method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        time.sleep(4)
        dev["dry_run"] = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/update/status", timeout=20)).get("message")
        js("[...document.querySelectorAll('.rows button')].find(b => b.textContent === 'Back Up').click()")
        wait("[...document.querySelectorAll('.rows button')].find(b => b.textContent === 'Back Up') && ![...document.querySelectorAll('.rows button')].find(b => b.textContent === 'Back Up').disabled", 90)
        dev["backup"] = js("document.querySelectorAll('.rows p')[1].textContent")
        js("[...document.querySelectorAll('.rows button')].find(b => b.textContent.startsWith('Restore')).click()")
        wait("!!document.querySelector('[aria-label=\"Restore from a Backup\"]')", 10)
        dev["restore_dialog"] = js("document.querySelector('[aria-label=\"Restore from a Backup\"] select')?.options.length")
        js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); document.querySelector('[aria-label=\"Restore from a Backup\"]')?.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        time.sleep(1)
        dev["restore_closed"] = js("!document.querySelector('[aria-label=\"Restore from a Backup\"]')")
        js("document.querySelector('.devrow .disc').click()")
        wait("document.querySelectorAll('.kids .item').length > 1", 40)
        dev["device_sidebar"] = js("document.querySelectorAll('.kids .item').length")
        say("DEVICE", dev)
    else:
        say("DEVICE", "skipped: no Y1 connected")

    js("openSmart()")
    wait("!!document.querySelector('.rule')", 15)
    smart = {"rules": js("document.querySelectorAll('.rule').length")}
    wait("/songs/.test(document.querySelector('[aria-live] , .line .small')?.textContent || '')", 10)
    smart["preview"] = js("[...document.querySelectorAll('.line .small')].map(e => e.textContent).join(' ')")
    js("document.querySelector('[role=dialog]').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    time.sleep(1)
    smart["closed"] = js("!document.querySelector('[role=dialog]')")
    say("SMART", smart)

    js("openPrefs()")
    wait("!!document.querySelector('[aria-label=Preferences]')", 15)
    prefs = {"open": js("!!document.querySelector('[aria-label=Preferences]')")}
    js("[...document.querySelectorAll('[role=tab]')].find(t => t.textContent === 'Devices').click()")
    time.sleep(1)
    prefs["swatches"] = js("document.querySelectorAll('.sw').length")
    js("document.querySelector('[role=dialog]').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    time.sleep(1)
    prefs["closed"] = js("!document.querySelector('[role=dialog]')")
    say("PREFS", prefs)

    js("[...document.querySelectorAll('.side .item')].find(b => b.textContent.trim() === 'Mixes').click()")
    wait("document.querySelectorAll('.cell').length > 0 || !!document.querySelector('.note')", 60)
    say("MIXES", {"mixes": js("document.querySelectorAll('.mosaic').length"), "note": js("document.querySelector('.wrap .note')?.textContent || ''")})
    say("ERRORS", js("window.__errors"))
    time.sleep(1)
    win.destroy()


if __name__ == "__main__":
    main()
