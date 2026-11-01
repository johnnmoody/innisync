<script>
  // About the Y1, its software (update, back up, restore, reflash, rescan, clock) and sync options.
  import RestoreDialog from "./RestoreDialog.svelte";
  import { st, refreshDevice, pollUpdate, UPDATE_ACTIVE } from "../../lib/store.svelte.js";
  import { api } from "../../lib/api.js";
  import { fmtSize, fmtWhen } from "../../lib/format.js";
  import { y1Svg } from "../../lib/y1.js";
  import { askText, confirm, notice } from "../../lib/dialogs.svelte.js";

  const d = $derived(st.device), s = $derived(st.settings);
  let upd = $state(null), updText = $state("Checking for newer Y1 software…"), updErr = $state(false);
  let backups = $state([]), backupFolder = $state(null), auto = $state({ state: "idle" });
  let backupText = $state(""), backupErr = $state(false), reflashText = $state(""), reflashErr = $state(false);
  let wifiText = $state(""), wifiBusy = $state(false), busy = $state(false), restoring = $state(false);
  const updating = $derived(UPDATE_ACTIVE.includes(st.update.state));
  const locked = $derived(busy || updating || auto.state === "running");

  async function checkUpdate(force) {
    updErr = false;
    if (force) updText = "Checking for newer Y1 software…";
    try { upd = await api("/api/update/check" + (force ? "?force=1" : "")); updText = upd.message; }
    catch (e) { upd = null; updText = `InniSync couldn't check for an update: ${e.message}`; updErr = true; }
  }
  let autoTimer;
  async function loadBackups() {
    clearTimeout(autoTimer);
    try {
      const r = await api("/api/device/backups");
      backups = r.backups; backupFolder = r.folder; auto = r.auto;
      if (auto.state === "running") { autoTimer = setTimeout(loadBackups, 2000); return; }
    } catch { backups = []; }
  }
  async function loadUpdater() {
    try {
      const u = await api("/api/updaterce");
      reflashText = u.installed ? `Innioasis Updater CE ${u.version} is on this computer${u.latest ? ` (latest release ${u.latest})` : ""}.`
        : `InniSync downloads Innioasis Updater CE${u.latest ? ` ${u.latest}` : ""} from GitHub for you to install.`;
    } catch { reflashText = ""; }
  }
  $effect(() => { checkUpdate(false); loadBackups(); loadUpdater(); return () => clearTimeout(autoTimer); });
  // when an update job finishes, show its result here
  $effect(() => {
    const u = st.update;
    if (UPDATE_ACTIVE.includes(u.state) || u.state === "done" || u.state === "error") { updText = u.message; updErr = u.state === "error"; }
    if (u.state === "done" && !u.dryRun) refreshOffer();   // the player app may have changed
  });
  async function refreshOffer() { try { upd = await api("/api/update/check"); } catch { /* the message already says what happened */ } }

  async function updateClick() {
    if (!upd?.update) return checkUpdate(true);
    if (!(await confirm(`Update to ${upd.app} ${upd.latest}?`, "InniSync backs up your Y1 first and keeps its settings. The player app restarts.", "Update"))) return;
    try { await api("/api/update/install", {}); pollUpdate(); } catch (e) { notice("The update didn't start", e.message); }
  }

  // InniClassic Autoplay: InniSync's build of the player, installed beside the original (see update.py)
  const onAutoplay = $derived(d.launcher_pkg === "com.themoon.y1.autoplay");
  async function useAutoplay() {
    const a = upd.autoplay;
    const ok = await confirm(`Switch to InniClassic Autoplay ${a.version}?`,
      "It's the same player with one addition: when your queue ends, it keeps playing songs that go with the last one, " +
      "picked by InniSync when it syncs. InniSync backs up your Y1, installs it beside InniClassic, and copies your " +
      "settings to it. InniClassic is turned off, not removed, so you can switch back.", "Switch");
    if (!ok) return;
    try {
      if (a.installed) { await api("/api/device/player-app", { app: "autoplay" }); updText = "Your Y1 plays with InniClassic Autoplay again."; await refreshDevice(true); refreshOffer(); }
      else { await api("/api/update/install", { switch: true }); pollUpdate(); }
    } catch (e) { notice("The switch didn't happen", e.message); }
  }
  async function useOriginal() {
    const ok = await confirm("Go back to InniClassic?",
      "Your Y1 switches back to the original InniClassic, with the settings it had. InniClassic Autoplay stays installed but off, so you can switch again later. The player app restarts.", "Switch Back");
    if (!ok) return;
    try { await api("/api/device/player-app", { app: "original" }); updText = "Your Y1 plays with InniClassic again."; await refreshDevice(true); refreshOffer(); }
    catch (e) { notice("The switch didn't happen", e.message); }
  }
  async function backUp() {
    busy = true; backupErr = false; backupText = "Backing up your Y1…";
    try { await api("/api/device/backup", {}); backupText = ""; await loadBackups(); }
    catch (e) { backupText = `The backup didn't finish: ${e.message}`; backupErr = true; }
    busy = false;
  }
  const INSTALL_STEP = {
    darwin: "Drag it to Applications in the window that opened, then click Reflash again.",
    win32: "Its installer is open: install it, then click Reflash again.",
    linux: "It's open. Follow its steps; InniSync finds the Y1 again when it's back.",
  };
  async function reflash() {
    busy = true; reflashErr = false; reflashText = "Backing up your Y1, then opening Innioasis Updater CE…";
    try {
      const r = await api("/api/updaterce/open", {});
      reflashText = (r.backup ? `Backed up as ${r.backup}. ` : "") + (r.opened === "app"
        ? "Innioasis Updater CE is open. Follow its steps; InniSync finds the Y1 again when it's back."
        : `Innioasis Updater CE ${r.tag} is downloaded and checked. ${INSTALL_STEP[st.prefs?.platform] || INSTALL_STEP.linux}`);
      loadBackups();
    } catch (e) { reflashText = e.message; reflashErr = true; }
    busy = false;
  }
  async function rename() {
    const n = await askText("Name your Y1", "", d.name, "Rename");
    if (n) { await api("/api/device/rename", { name: n }); refreshDevice(true); }
  }
  async function rescan() { await api("/api/device/rescan", {}); notice("Rescanning", "Your Y1 is rebuilding its library. The player app restarted to do it."); }
  async function fixClock() { await api("/api/device/fixclock", {}); refreshDevice(true); }
  async function wifi(e) {
    const on = e.currentTarget.checked; wifiBusy = true; wifiText = on ? "Turning on…" : "Turning off…";
    try { const r = await api("/api/device/wifi", { on }); wifiText = on ? `On: the Y1 is at ${r.ip}, and only this computer can connect.` : ""; }
    catch (err) { wifiText = err.message; }
    wifiBusy = false; refreshDevice(true);
  }
  const last = $derived(backups[0]);
</script>

<div class="card about">
  <div class="art" aria-hidden="true">{@html y1Svg(st.y1Color)}</div>
  <dl>
    <dt>Name</dt><dd>{d.name} <button class="link" onclick={rename}>Rename</button></dd>
    <dt>Capacity</dt><dd>{fmtSize(d.capacity)}</dd>
    <dt>System</dt><dd>{d.firmware} (Android {d.android})</dd>
    <dt>Player app</dt><dd>{d.launcher ? `${d.launcher_pkg === "com.themoon.y1.autoplay" ? "InniClassic Autoplay" : "InniClassic"} ${d.launcher}` : "Not installed"}</dd>
    <dt>Battery</dt><dd>{d.battery != null ? `${d.battery}%${d.charging ? ", charging" : ""}` : "Unknown"}</dd>
    <dt>Wi-Fi</dt><dd>{d.wifi || "Not connected"}</dd>
    <dt>Connected by</dt><dd>{d.transport === "wifi" ? "Wi-Fi" : "USB"}</dd>
  </dl>
</div>

<div class="card">
  <h2>Software and backups</h2>
  <div class="rows">
    <button disabled={locked} onclick={updateClick}>{upd?.update ? "Update" : "Check for Update"}</button>
    <p class:err={updErr}>{updText}</p>

    {#if upd?.autoplay && !onAutoplay}
      <button disabled={locked} onclick={useAutoplay}>Use Autoplay…</button>
      <p>InniClassic Autoplay {upd.autoplay.version} is InniSync's build of the player. When your queue ends, it keeps playing songs that go with the last one. Your settings come with it.</p>
    {:else if onAutoplay}
      <button disabled={locked} onclick={useOriginal}>Use InniClassic…</button>
      <p>Your Y1 runs InniClassic Autoplay. You can switch back to the original InniClassic at any time; its settings are still there.</p>
    {/if}

    <button disabled={locked} onclick={backUp}>Back Up</button>
    <p class:err={backupErr}>{auto.state === "running" ? "Backing up your Y1 automatically…" : backupText ||
      `${last ? `Last backed up ${fmtWhen(last.created)}, on ${last.where}. ` : ""}Saves the player's settings, playlists, library index and play log${backupFolder ? ` to ${backupFolder}` : " on this computer"}.`}</p>

    <button disabled={locked || !backups.length} onclick={() => (restoring = true)}>Restore…</button>
    <p>Puts the player's settings and playlists back from a backup, if something on the Y1 has gone wrong.</p>

    <button disabled={locked} onclick={reflash}>Reflash…</button>
    <p class:err={reflashErr}>To install different firmware, or fix a Y1 that won't start, use Innioasis Updater CE. InniSync backs up the Y1 first. {reflashText}</p>

    <button disabled={locked} onclick={rescan}>Rescan Library</button>
    <p>If songs you copied don't show up on the Y1, rescan its library. The player app restarts.</p>

    {#if !d.clock_ok}
      <button onclick={fixClock}>Fix Clock</button>
      <p>The Y1's clock is wrong (it resets when the battery runs flat). Set it from this computer.</p>
    {/if}
  </div>
</div>

{#if s}
  <div class="card opts">
    <h2>Options</h2>
    <label title="When the cable is out, InniSync reaches the Y1 over your network. Only this computer can connect, and restarting the Y1 turns it off."><input type="checkbox" checked={!!d.wifi_sync} disabled={wifiBusy} onchange={wifi} /> Sync with this Y1 over Wi-Fi <span class="muted small">{wifiText}</span></label>
    <label><input type="checkbox" bind:checked={s.convert} /> Convert lossless songs to 320 kbps MP3</label>
    <label title="Plays logged on the Y1 count on your music server, so play counts and recently played include them."><input type="checkbox" bind:checked={s.play_counts} /> Send play counts to your music server when syncing</label>
    <label title="Only timed lyrics are copied. The Y1 shows lyrics embedded in a song by itself."><input type="checkbox" bind:checked={s.lyrics} /> Copy timed lyrics, shown on the Y1's Now Playing screen</label>
    <label class="sub" title="LRCLIB is a free, open lyrics library. Its address is in Preferences, Advanced."><input type="checkbox" bind:checked={s.lyrics_lrclib} disabled={!s.lyrics} /> Look up missing timed lyrics on LRCLIB</label>
    <p class="note">Wi-Fi on the Y1 is slow, so over Wi-Fi InniSync sends play counts and shows the Y1's status. Music copies over USB.</p>
  </div>
{/if}

{#if restoring}<RestoreDialog {backups} onclose={() => (restoring = false)} ondone={(msg) => { restoring = false; backupText = msg; loadBackups(); refreshDevice(true); }} />{/if}

<style>
  .about { display: flex; gap: 24px; align-items: flex-start; }
  .art { width: 84px; height: 133px; flex: none; }
  .art :global(svg) { width: 100%; height: 100%; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 4px 0 0; }
  dt { color: var(--text-2); }
  dd { margin: 0; }
  .rows { display: grid; grid-template-columns: 150px 1fr; gap: 12px 16px; align-items: start; }
  .rows button { width: 100%; }
  .rows p { margin: 4px 0 0; font-size: 13px; color: var(--text-2); }
  .rows p.err { color: var(--danger); }
  .opts label { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
  .opts label.sub { margin-left: 24px; }
  .small { font-size: 12px; }
</style>
