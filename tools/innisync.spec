# PyInstaller recipe for the downloadable InniSync (run through tools/build_release.py, which draws the icons first).
# One folder with Python and every package inside; on macOS wrapped as InniSync.app.
import os
import re
import sys

ROOT = os.path.dirname(SPECPATH)
BUILD = os.path.join(ROOT, "build")
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "innisync", "__init__.py")).read()).group(1)
ICON = os.path.join(BUILD, "InniSync.icns" if sys.platform == "darwin" else "InniSync.ico")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "innisync", "web"), "innisync/web"), (os.path.join(BUILD, "icons"), "icons")],
    hiddenimports=["keyring.backends"] if sys.platform != "darwin" else [],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="InniSync", console=False, icon=ICON,
          target_arch=None, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="InniSync")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="InniSync.app", icon=ICON, bundle_identifier="io.github.johnnmoody.innisync",
                 version=VERSION, info_plist={
                     "CFBundleDisplayName": "InniSync",
                     "CFBundleShortVersionString": VERSION,
                     "LSMinimumSystemVersion": "12.0",
                     "NSHighResolutionCapable": True,
                     "NSLocalNetworkUsageDescription": "InniSync reads your music from your Jellyfin or Subsonic server.",
                 })
