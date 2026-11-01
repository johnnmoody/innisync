# InniSync

A desktop companion for the **Innioasis Y1** music player: your music library from Jellyfin or a Subsonic server
(such as Navidrome) on one side, the Y1 on the other.

InniSync is an unofficial project. It is not made by or affiliated with Innioasis or Apple.

## What it does
- **Library:** browse and play your Jellyfin or Subsonic library (songs, albums, covers, playlists, smart playlists).
- **Sync to the Y1 over USB:** your whole library or chosen playlists, artists and genres, with a preview of the
  space it takes. Lossless songs can be converted to 320 kbps MP3 to fit more.
- **Mixes and similar songs:** InniSync listens to the songs on your Y1 and groups the ones that sound alike.
  With InniClassic Autoplay (below) the Y1 keeps playing matching songs when its queue ends.
- **Play counts:** plays logged on the Y1 are counted on your music server when you sync.
- **Lyrics:** timed lyrics from your server, or from LRCLIB.
- **Podcasts and audiobooks:** episodes into InniClassic's own Podcasts menu, books into its Audiobooks folder.
- **Themes and settings:** InniClassic themes, wallpaper, and the player's own settings.
- **Updates, backups, restore:** InniClassic updates from GitHub (checked by digest), backups of the player's
  settings and playlists, restore, and a hand-off to Innioasis Updater CE for reflashing.
- **Wi-Fi:** see the Y1's status and send play counts without the cable. The Y1's Wi-Fi is too slow for music,
  so that still copies over USB. Only your computer can connect, and restarting the Y1 turns it off.

## Requirements
- macOS 12 or later, for now. The interface is the same everywhere; Windows and Linux builds are planned.
- Python 3.12 or later, Node 20 or later, and `adb` and `ffmpeg` (for example from Homebrew).
- A Y1 running InniClassic, with USB debugging available (it is on InniClassic's stock firmware).

## Build and run
```bash
bash tools/build_app.sh        # builds the interface and /Applications/InniSync.app
```
For development, run the server and the interface separately:
```bash
python3 run.py --server-only   # the API on 127.0.0.1:8765
cd ui && npm run dev           # the interface, with the API proxied
```
`run.py --selftest` drives the real app window through every area and writes the results to
`~/Library/Logs/InniSync.log`.

## Layout
- `innisync/` the server: library clients (`jellyfin.py`, `subsonic.py`), the Y1 over adb (`device.py`), sync
  (`sync.py`), sound analysis (`soundalike.py`), smart playlists, podcasts, play counts, lyrics, backups, updates,
  Wi-Fi, and the menu-bar item.
- `ui/` the interface (Svelte). `DESIGN.md` holds its design direction.
- `tools/` the app build and the icon drawing.

## InniClassic Autoplay
Autoplay needs a small change to InniClassic, the Y1's player app, published separately as InniClassic Autoplay.
It installs beside the original InniClassic and reads the matches InniSync writes on each sync.
InniClassic is by FabianZettl and is free for personal, non-commercial use.

## Credits
- [InniClassic](https://github.com/FabianZettl/inniclassic) by FabianZettl
- [Atkinson Hyperlegible Next](https://github.com/googlefonts/atkinson-hyperlegible-next), SIL Open Font License
- [LRCLIB](https://lrclib.net) for timed lyrics
- [Innioasis Updater CE](https://github.com/y1-community/Innioasis-Updater) by the Y1 community

## License
MIT, see `LICENSE`. The bundled Atkinson Hyperlegible Next font is under the SIL Open Font License
(`ui/src/fonts/OFL.txt`). InniClassic Autoplay is a separate project under InniClassic's own license.
