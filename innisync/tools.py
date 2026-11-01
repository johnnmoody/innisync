"""Where InniSync finds its command-line helpers (adb, ffmpeg, the Android build tools, Java).

Looked up in order: an environment override (INNISYNC_ADB, INNISYNC_FFMPEG, ...), a bin/ folder shipped next to the
code (the packaged app bundles adb and ffmpeg there), PATH, then the usual Homebrew and /usr/local places, since an
app opened from the Finder gets a minimal PATH.
"""
import glob
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = [os.path.join(HERE, "..", "bin"), os.path.join(HERE, "..", "..", "bin")]
EXTRA = ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/Library/Android/sdk/platform-tools")]


def find(name, env=None):
    """Full path to a helper, or the bare name (so a missing tool fails with a clear "not found" when it's used)."""
    if env and os.environ.get(env):
        return os.environ[env]
    for d in BUNDLED:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return os.path.abspath(p)
    return shutil.which(name, path=os.pathsep.join([os.environ.get("PATH", ""), *EXTRA])) or name


def build_tool(name):
    """aapt2 / apksigner from the newest Android SDK build-tools found, or None."""
    roots = [os.environ.get("ANDROID_HOME", ""), os.environ.get("ANDROID_SDK_ROOT", ""),
             "/opt/homebrew/share/android-commandlinetools", os.path.expanduser("~/Library/Android/sdk")]
    found = sorted(p for r in roots if r for p in glob.glob(os.path.join(r, "build-tools", "*", name)))
    return found[-1] if found else None


def java_home():
    """A JDK for apksigner, or None."""
    for p in [os.environ.get("JAVA_HOME", ""), "/opt/homebrew/opt/openjdk@17", "/opt/homebrew/opt/openjdk",
              "/usr/local/opt/openjdk@17", "/usr/local/opt/openjdk"]:
        if p and os.path.isfile(os.path.join(p, "bin", "java")):
            return p
    return None
