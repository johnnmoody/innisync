// App state and the actions that change it. Components read `st` and call these functions.
import { api } from "./api.js";
import { applyAccent } from "./accent.js";

export const st = $state({
  // library
  songs: [], byId: {}, playlists: [], plItems: {}, loadedAt: 0, libError: "", libLoading: true, signedOut: false,
  // where we are
  view: "music", playlist: null, devPl: null, search: "",
  genre: null, artist: null, album: null, showBrowser: false,
  sort: { key: "artist", dir: 1 }, mode: "list", gridBy: "albums",
  selected: null, status: "",
  // playback on this computer
  playing: null, queue: [], qpos: -1, shuffle: false, repeat: false, paused: true, time: 0, duration: 0, volume: 0.7,
  // the Y1
  device: null, settings: null, saved: null, tab: "summary", plan: null, devOpen: false, dev: null,
  player: null, playerSaved: null,
  // background jobs shown in the now-playing bar
  sync: { state: "idle" }, update: { state: "idle" },
  // sound-alike features
  similar: { seed: null, items: [], kept: false }, keptSeeds: [], mixes: null, analysis: null,
  // preferences
  prefs: null, y1Color: "black", accentKey: "black",
});

// ---------------- library ----------------
export async function loadLibrary(refresh) {
  st.libLoading = true;
  try {
    const lib = await api("/api/library" + (refresh ? "?refresh=1" : ""));
    st.songs = lib.songs; st.playlists = lib.playlists; st.plItems = lib.playlistItems; st.loadedAt = lib.loadedAt;
    st.byId = Object.fromEntries(lib.songs.map((s) => [s.id, s]));
    st.libError = ""; st.signedOut = false;
  } catch (e) {
    st.signedOut = !!e.signIn; st.libError = e.signIn ? "" : e.message;
    if (e.signIn) { st.songs = []; st.playlists = []; st.byId = {}; }
  }
  st.libLoading = false;
}

const genresOf = (s) => (s.genres.length ? s.genres : ["Unknown"]);
const artistOf = (s) => s.albumArtist || s.artist || "Unknown Artist";

export function baseSongs() {
  let list = st.songs;
  if (st.view === "playlist") list = (st.plItems[st.playlist] || []).map((id) => st.byId[id]).filter(Boolean);
  else if (st.view === "devmusic") list = st.dev ? st.dev.songs : [];
  else if (st.view === "devpl") {
    const pl = (st.dev?.playlists || []).find((p) => p.id === st.devPl);
    const byId = Object.fromEntries((st.dev?.songs || []).map((s) => [s.id, s]));
    list = (pl?.items || []).map((id) => byId[id]).filter(Boolean);
  } else if (st.view === "recent") list = [...st.songs].sort((a, b) => (b.added || "").localeCompare(a.added || "")).slice(0, 300);
  else if (st.view === "similar") list = st.similar.items.map((id) => st.byId[id]).filter(Boolean);
  if (st.search) {
    const q = st.search.toLowerCase();
    list = list.filter((s) => `${s.name} ${s.artist} ${s.album} ${s.albumArtist}`.toLowerCase().includes(q));
  }
  return list;
}

const last = (v) => v || "￿";   // untagged songs sort after everything
export function visibleSongs() {
  let list = baseSongs().filter((s) =>
    (!st.genre || genresOf(s).includes(st.genre)) &&
    (!st.artist || artistOf(s) === st.artist) &&
    (!st.album || (s.album || "Unknown Album") === st.album));
  if (!["playlist", "devpl", "similar"].includes(st.view)) {   // these keep their own order
    const { key: k, dir } = st.sort;
    const val = (s) => k === "genre" ? last(s.genres[0])
      : k === "artist" ? `${last(artistOf(s) === "Unknown Artist" ? "" : artistOf(s))}\u0000${last(s.album)}\u0000${String(s.disc || 1).padStart(2, "0")}${String(s.track || 0).padStart(3, "0")}`
      : k === "album" ? last(s.album) : s[k] ?? "";
    list = [...list].sort((x, y) => { const a = val(x), b = val(y); return (typeof a === "number" ? a - b : String(a).localeCompare(String(b))) * dir; });
  }
  return list;
}

export function browserColumns() {
  const base = baseSongs();
  const unkLast = (u) => (a, b) => (a === u) - (b === u) || a.localeCompare(b);
  const genres = [...new Set(base.flatMap(genresOf))].sort(unkLast("Unknown"));
  const g = base.filter((s) => !st.genre || genresOf(s).includes(st.genre));
  const artists = [...new Set(g.map(artistOf))].sort(unkLast("Unknown Artist"));
  const a = g.filter((s) => !st.artist || artistOf(s) === st.artist);
  const albums = [...new Set(a.map((s) => s.album || "Unknown Album"))].sort(unkLast("Unknown Album"));
  return { genres, artists, albums };
}

export function albumGroups(rows) {
  const groups = [], idx = {};
  rows.forEach((s) => {
    const k = `${artistOf(s)}\u0000${s.album}`;
    if (!(k in idx)) { idx[k] = groups.length; groups.push({ key: k, album: s.album || "Unknown Album", artist: artistOf(s), art: s.albumId || s.id, year: s.year, items: [] }); }
    groups[idx[k]].items.push(s);
  });
  return groups;
}

export function gridGroups(rows) {
  if (st.gridBy === "albums")
    return albumGroups(rows).map((g) => ({ ...g, title: g.album, sub: g.artist + (g.year ? ` · ${g.year}` : ""), filter: { artist: g.artist, album: g.album } }));
  const m = new Map();
  rows.forEach((s) => {
    for (const k of st.gridBy === "artists" ? [artistOf(s)] : genresOf(s)) {
      if (!m.has(k)) m.set(k, { key: k, title: k, art: s.albumId || s.id, items: [], albums: new Set() });
      m.get(k).items.push(s); m.get(k).albums.add(s.album);
    }
  });
  const unk = st.gridBy === "artists" ? "Unknown Artist" : "Unknown";
  return [...m.values()].sort((a, b) => (a.title === unk) - (b.title === unk) || a.title.localeCompare(b.title))
    .map((g) => ({ ...g, sub: `${g.albums.size} ${g.albums.size === 1 ? "album" : "albums"}`, filter: st.gridBy === "artists" ? { artist: g.title } : { genre: g.title } }));
}

export function clearFilters() { st.genre = st.artist = st.album = null; }

export function go(view, extra = {}) {
  st.view = view; st.playlist = extra.playlist ?? null; st.devPl = extra.devPl ?? null;
  clearFilters();
  if (view === "device") refreshDevice(true);
  if (view === "mixes") loadMixes();
}

export function toggleBrowser(on) {
  st.showBrowser = on ?? !st.showBrowser;
  if (!st.showBrowser) clearFilters();
  api("/api/prefs", { ...st.prefs, show_browser: st.showBrowser }).then((p) => (st.prefs = p)).catch(() => {});
}

export async function newPlaylist(name) {
  await api("/api/playlists", { name });
  await loadLibrary(true);
}

// ---------------- playback (on this computer, streamed through the local server) ----------------
export const audio = typeof Audio !== "undefined" ? new Audio() : null;
if (audio) {
  audio.preload = "none";
  audio.volume = st.volume;
  audio.addEventListener("timeupdate", () => { st.time = audio.currentTime; st.duration = audio.duration || st.byId[st.playing]?.duration || 0; });
  audio.addEventListener("ended", () => step(1));
  audio.addEventListener("play", () => (st.paused = false));
  audio.addEventListener("pause", () => (st.paused = true));
}

export function play(id, queue) {
  const s = st.byId[id];
  if (!s || s.deviceOnly) { st.status = "This song is only on the Y1 (added outside InniSync), so it can't play here."; return; }
  if (queue) { st.queue = queue; st.qpos = queue.indexOf(id); }
  st.playing = id; st.selected = st.selected ?? id;
  audio.src = `/stream/${encodeURIComponent(id)}`;
  audio.play().catch((e) => { if (e.name === "AbortError" && st.playing === id) setTimeout(() => audio.play().catch(() => {}), 300); });
}
export function step(dir) {
  if (!st.queue.length) return;
  let q = st.shuffle ? Math.floor(Math.random() * st.queue.length) : st.qpos + dir;
  if (q >= st.queue.length) { if (!st.repeat) return; q = 0; }
  st.qpos = Math.max(q, 0);
  play(st.queue[st.qpos]);
}
export function togglePlay(rows) {
  if (!st.playing) { const first = rows.find((r) => !r.deviceOnly); if (first) play(first.id, rows.filter((r) => !r.deviceOnly).map((r) => r.id)); return; }
  audio.paused ? audio.play() : audio.pause();
}
export function previous() { if (audio.currentTime > 3) audio.currentTime = 0; else step(-1); }
export function seek(fraction) { const d = audio.duration || st.duration; if (d) audio.currentTime = Math.min(Math.max(fraction, 0), 1) * d; }
export function setVolume(v) { st.volume = Math.min(Math.max(v, 0), 1); audio.volume = st.volume; }

// ---------------- the Y1 ----------------
export const dirty = () => JSON.stringify(st.settings) !== JSON.stringify(st.saved);
export const playerDirty = () => !!st.player && JSON.stringify(st.player) !== JSON.stringify(st.playerSaved);
let lastSerial = null;
let onConnect = () => {};
export function whenConnected(fn) { onConnect = fn; }

export async function refreshDevice(force) {
  try {
    const d = await api("/api/device" + (force ? "?refresh=1" : ""));
    const was = !!st.device;
    st.device = d.connected ? d : null;
    if (st.device) {
      if (!was || force || !st.saved) { st.settings = structuredClone(d.settings); st.saved = structuredClone(d.settings); }
      if (!was) onConnect();
      if (d.serial !== lastSerial) maybeAutoSync();
      lastSerial = d.serial;
    } else {
      lastSerial = null; st.dev = null; st.player = st.playerSaved = null;
      if (["device", "devmusic", "devpl"].includes(st.view)) go("music");
    }
  } catch { /* server busy: the next poll tries again */ }
}

export async function loadDeviceContents() {
  if (!st.device) return;
  try { st.dev = await api("/api/device/contents"); } catch { st.dev = { songs: [], playlists: [] }; }
  for (const s of st.dev.songs) if (!s.deviceOnly && !st.byId[s.id]) st.byId[s.id] = s;
}

let planTimer;
export function updatePlan() {
  clearTimeout(planTimer);
  planTimer = setTimeout(async () => {
    try { st.plan = await api("/api/device/plan", st.settings); } catch { st.plan = null; }
  }, 250);
}

export async function startSync() {
  await api("/api/device/sync", st.settings);
  st.saved = structuredClone(st.settings);
  pollSync();
}

async function maybeAutoSync() {
  const p = st.prefs || (await api("/api/prefs").catch(() => null));
  const s = await api("/api/sync/status").catch(() => ({}));
  if (p?.auto_sync && !["starting", "checking", "syncing"].includes(s.state)) {
    await api("/api/device/sync", {}).catch(() => {});
    pollSync();
  }
}

const SYNC_ACTIVE = ["starting", "checking", "syncing"];
export const UPDATE_ACTIVE = ["starting", "downloading", "verifying", "backing_up", "installing"];
let syncTimer, syncClear;
export async function pollSync(background) {
  clearTimeout(syncTimer);
  const s = await api("/api/sync/status").catch(() => ({ state: "idle" }));
  const active = SYNC_ACTIVE.includes(s.state);
  if (background && !active) return;
  clearTimeout(syncClear);
  st.sync = s;
  if (active) { syncTimer = setTimeout(pollSync, 1000); return; }
  if (s.state !== "idle") {
    refreshDevice(true);
    setTimeout(() => { st.dev = null; if (st.devOpen) loadDeviceContents(); }, 20000);
    // a clean finish fades; problems and stops stay until dismissed, so they can be read and fixed
    if (s.state === "done" && !s.errors?.length) syncClear = setTimeout(() => (st.sync = { state: "idle" }), 8000);
  }
}
export const syncing = () => SYNC_ACTIVE.includes(st.sync.state);
export const dismissSync = () => { clearTimeout(syncClear); st.sync = { state: "idle" }; };

// the fix for a sync that stopped because it would take most songs off: the user says it's meant
export async function syncAllowingRemovals() {
  await api("/api/device/sync", { allow_removals: true });
  pollSync();
}

// the fix for a damaged sync record: rebuild it from the files on the Y1, then say what was found
export async function rebuildRecord() {
  const r = await api("/api/device/manifest/rebuild", {});
  st.sync = { state: "idle" };
  st.status = `Rebuilt the Y1's record: ${r.songs} songs and ${r.playlists} playlists found` +
    (r.unmatched ? `, ${r.unmatched} other files left alone.` : ".");
  return r;
}

let updTimer;
export async function pollUpdate(background) {
  clearTimeout(updTimer);
  const s = await api("/api/update/status").catch(() => ({ state: "idle" }));
  const active = UPDATE_ACTIVE.includes(s.state);
  if (s.state === "idle" || (background && !active)) return;
  st.update = s;
  if (active) { updTimer = setTimeout(pollUpdate, 700); return; }
  setTimeout(() => (st.update = { state: "idle", last: s }), 8000);
  if (s.state === "done" && !s.dryRun) await refreshDevice(true);
}

// ---------------- similar songs and mixes ----------------
export async function openSimilar(seed) {
  if (!seed) { st.status = "Select a song first, then click Similar Songs."; return; }
  try {
    const r = await api(`/api/similar/songs?id=${encodeURIComponent(seed)}`);
    st.similar = { seed, items: r.items, kept: r.kept };
    st.view = "similar"; clearFilters();
  } catch (e) { st.status = e.message; }
}
export async function keepSimilar() {
  const s = await api("/api/similar/keep", { id: st.similar.seed, keep: !st.similar.kept });
  st.similar.kept = !st.similar.kept; st.keptSeeds = s.similar_seeds;
  if (st.settings) { st.settings.similar_seeds = [...s.similar_seeds]; st.saved.similar_seeds = [...s.similar_seeds]; }
  st.status = st.similar.kept ? "These similar songs go to your Y1 on the next sync." : "Removed. They come off your Y1 on the next sync.";
}
export async function loadMixes() {
  try { st.mixes = (await api("/api/similar/mixes")).mixes; } catch { st.mixes = []; }
}
export async function pollAnalysis() {
  const g = await api("/api/similar/status").catch(() => null);
  if (!g) return;
  const was = st.analysis?.state;
  st.analysis = g; st.keptSeeds = g.seeds || [];
  if (was === "analyzing" && g.state !== "analyzing" && st.view === "mixes") loadMixes();
}

// ---------------- preferences ----------------
export async function loadPrefs() {
  st.prefs = await api("/api/prefs");
  st.showBrowser = !!st.prefs.show_browser;
  st.y1Color = st.prefs.y1_color || "black";
  st.accentKey = st.prefs.accent === "grey" ? "grey" : st.y1Color;
  applyAccent(st.accentKey);
}
export async function savePrefs(changes) {
  st.prefs = await api("/api/prefs", { ...st.prefs, ...changes });
  st.y1Color = st.prefs.y1_color;
  st.accentKey = st.prefs.accent === "grey" ? "grey" : st.y1Color;
  applyAccent(st.accentKey);
}
if (typeof matchMedia !== "undefined")
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyAccent(st.accentKey));
