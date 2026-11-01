"""Build the downloadable InniSync for this system into dist/: InniSync-<version>-macos.zip (InniSync.app),
-windows.zip or -linux.tar.gz (a folder with InniSync inside). Build the interface first (cd ui && npx vite build),
and install requirements-build.txt. CI runs this on each system for a release (.github/workflows/release.yml)."""
import os
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD, DIST = os.path.join(ROOT, "build"), os.path.join(ROOT, "dist")
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "innisync", "__init__.py")).read()).group(1)
SYSTEM = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def main():
    if not os.path.isfile(os.path.join(ROOT, "innisync", "web", "index.html")):
        sys.exit("Build the interface first: cd ui && npm ci && npx vite build")
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    icons = os.path.join(BUILD, "icons")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_icons.py"), icons], check=True)
    from PIL import Image
    big = Image.open(os.path.join(icons, "black.png"))
    if SYSTEM == "macos":
        big.save(os.path.join(BUILD, "InniSync.icns"))
    else:
        big.save(os.path.join(BUILD, "InniSync.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
                    "--workpath", os.path.join(BUILD, "pyinstaller"), os.path.join(ROOT, "tools", "innisync.spec")],
                   check=True)
    name = f"InniSync-{VERSION}-{SYSTEM}"
    if SYSTEM == "macos":
        out = os.path.join(DIST, name + ".zip")   # ditto keeps the app's symlinks and permissions
        subprocess.run(["ditto", "-c", "-k", "--keepParent", os.path.join(DIST, "InniSync.app"), out], check=True)
    elif SYSTEM == "windows":
        out = shutil.make_archive(os.path.join(DIST, name), "zip", DIST, "InniSync")
    else:
        out = os.path.join(DIST, name + ".tar.gz")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(os.path.join(DIST, "InniSync"), arcname="InniSync")
    print(out)


if __name__ == "__main__":
    main()
