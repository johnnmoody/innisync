"""What differs between macOS, Windows and Linux: where InniSync keeps its files and log, where sign-ins are stored,
the computer's timezone, and opening a file with its app.

Sign-ins: on macOS they stay in the login Keychain through the `security` tool, exactly where earlier versions put
them. On Windows (Credential Manager) and Linux (Secret Service: GNOME Keyring, KWallet) they go through the
`keyring` package.
"""
import os
import subprocess
import sys

MAC, WINDOWS = sys.platform == "darwin", sys.platform == "win32"
LINUX = not MAC and not WINDOWS


def data_dir():
    if os.environ.get("INNISYNC_DATA"):
        return os.path.expanduser(os.environ["INNISYNC_DATA"])
    if MAC:
        return os.path.expanduser("~/Library/Application Support/InniSync")
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "InniSync")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "InniSync")


def log_path():
    if MAC:
        return os.path.expanduser("~/Library/Logs/InniSync.log")
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or data_dir(), "InniSync", "InniSync.log")
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "InniSync", "InniSync.log")


# ---- sign-ins ----
def secret_get(service, account):
    if MAC:
        p = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    import keyring
    return keyring.get_password(service, account)


def secret_set(service, account, secret):
    if MAC:
        subprocess.run(["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret],
                       check=True, capture_output=True)
        return
    import keyring
    keyring.set_password(service, account, secret)


def secret_delete(service, account):
    if MAC:
        subprocess.run(["security", "delete-generic-password", "-s", service, "-a", account], capture_output=True)
        return
    import keyring
    import keyring.errors
    try:
        keyring.delete_password(service, account)
    except keyring.errors.PasswordDeleteError:
        pass   # already gone


def timezone():
    """This computer's timezone name (e.g. Europe/Berlin), for the Y1's clock."""
    if WINDOWS:
        import tzlocal
        return tzlocal.get_localzone_name() or "UTC"
    real = os.path.realpath("/etc/localtime")
    return real.split("zoneinfo/", 1)[1] if "zoneinfo/" in real else "UTC"


def open_path(path):
    """Open a file or folder the way double-clicking it would."""
    if WINDOWS:
        os.startfile(path)   # noqa: S606 (a path InniSync downloaded and checked)
    else:
        subprocess.run(["open" if MAC else "xdg-open", path], check=True, timeout=60)


if WINDOWS:
    # adb and ffmpeg are console programs: started from a windowed app, each would flash a console window.
    _popen_init = subprocess.Popen.__init__

    def _no_console(self, *args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        _popen_init(self, *args, **kwargs)
    subprocess.Popen.__init__ = _no_console
