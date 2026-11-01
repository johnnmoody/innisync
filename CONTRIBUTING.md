# Contributing

Bug reports, fixes and ideas are welcome. For anything bigger than a small fix, open an issue first so we can agree
on the shape before you spend time on it.

## Running it from source
See [Development](README.md#development) in the README. In short: `python3 run.py --server-only` for the API, and
`npm run dev` in `ui/` for the interface.

## Tests
```bash
pip install -r requirements-dev.txt
```
```bash
cd ui && npm ci && npx vite build && cd ..
```
```bash
python -m pytest -q
```
- `tests/fakes.py` has a pretend Y1 (files in memory, a small adb shell), so most tests need no device or server.
- `tests/integration/` runs against a real Navidrome with three generated songs. It is skipped unless Navidrome and
  ffmpeg are installed; point `INNISYNC_NAVIDROME` at the binary. CI runs it on Linux and macOS.
- `python3 run.py --selftest` opens the real window and clicks through every area. It needs a Mac and a signed-in
  library, and writes its results to `~/Library/Logs/InniSync.log`.

## Things to keep in mind
- **The Y1 holds someone's music.** Anything that deletes or overwrites on the Y1 must fail safe: when InniSync can't
  tell what is there, it stops and says so instead of guessing. Add a test with the fake Y1 for any change to sync,
  removal or the sync record.
- **adb on the Y1 is a root shell.** Quote every path you put in a shell command (`shlex.quote`), and keep paths
  inside the folder they belong to.
- **The local server only answers InniSync's own page.** Requests to `/api/` need the `X-InniSync: 1` header and
  must come from `127.0.0.1` or `localhost`. Don't loosen that.
- **No accounts, trackers or paid services.** Fonts and icons are bundled; nothing loads from a CDN.
- **Interface:** follow `DESIGN.md`. Every warning comes with a way to fix it (a button or a clear next step).
- Pin new dependencies to an exact version.
