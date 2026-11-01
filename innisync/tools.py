"""Where InniSync finds its command-line helpers (adb, ffmpeg, the Android build tools, Java).

Looked up in order: an environment override (INNISYNC_ADB, INNISYNC_FFMPEG, ...), a bin/ folder next to the code,
PATH, then the usual install places (Homebrew, /usr/local, the Android SDK), since an app opened from the Finder or
the Start menu gets a minimal PATH.
"""
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = [os.path.join(HERE, "..", "bin"), os.path.join(HERE, "..", "..", "bin")]
EXTRA = ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/Library/Android/sdk/platform-tools"),
         os.path.expanduser("~/Android/Sdk/platform-tools"),
         os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools")]
EXE = ".exe" if sys.platform == "win32" else ""


def find(name, env=None):
    """Full path to a helper, or the bare name (so a missing tool fails with a clear "not found" when it's used)."""
    if env and os.environ.get(env):
        return os.environ[env]
    for d in BUNDLED:
        p = os.path.join(d, name + EXE)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return os.path.abspath(p)
    return shutil.which(name, path=os.pathsep.join([os.environ.get("PATH", ""), *EXTRA])) or name


def build_tool(name):
    """aapt2 / apksigner from the newest Android SDK build-tools found, or None."""
    roots = [os.environ.get("ANDROID_HOME", ""), os.environ.get("ANDROID_SDK_ROOT", ""),
             "/opt/homebrew/share/android-commandlinetools", os.path.expanduser("~/Library/Android/sdk"),
             os.path.expanduser("~/Android/Sdk"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")]
    if sys.platform == "win32":
        name = "apksigner.bat" if name == "apksigner" else name + EXE   # apksigner is a script there
    found = sorted(p for r in roots if r for p in glob.glob(os.path.join(r, "build-tools", "*", name)))
    return found[-1] if found else None


def java_home():
    """A JDK for apksigner, or None."""
    for p in [os.environ.get("JAVA_HOME", ""), "/opt/homebrew/opt/openjdk@17", "/opt/homebrew/opt/openjdk",
              "/usr/local/opt/openjdk@17", "/usr/local/opt/openjdk"]:
        if p and os.path.isfile(os.path.join(p, "bin", "java" + EXE)):
            return p
    return None
