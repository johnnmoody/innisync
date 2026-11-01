<script>
  import TopBar from "./components/TopBar.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import LibraryView from "./components/LibraryView.svelte";
  import StatusBar from "./components/StatusBar.svelte";
  import DeviceView from "./components/device/DeviceView.svelte";
  import Preferences from "./components/Preferences.svelte";
  import SmartEditor from "./components/SmartEditor.svelte";
  import Dialogs from "./components/Dialogs.svelte";
  import { dlg, askText, notice } from "./lib/dialogs.svelte.js";
  import {
    st, loadLibrary, loadPrefs, refreshDevice, pollSync, pollUpdate, pollAnalysis, whenConnected, visibleSongs,
    togglePlay, step, previous, setVolume, play, toggleBrowser, dirty, playerDirty, syncing, newPlaylist,
  } from "./lib/store.svelte.js";
  import { api } from "./lib/api.js";

  let prefsOpen = $state(null);   // null, or {pane, signIn}
  let smartId = $state(undefined); // undefined = closed, null = new, "<id>" = edit
  let searchEl = $state();
  const rows = $derived(visibleSongs());

  function openPrefs(pane = "general", signIn = false) { prefsOpen = { pane, signIn }; }
  function openSmart(id = null) { smartId = id; }
  async function newList() {
    const name = await askText("New Playlist", "", "untitled playlist", "Create");
    if (name) newPlaylist(name).catch((e) => notice("The playlist wasn't created", e.message));
  }
  // the native menu bar (run.py) calls these
  Object.assign(window, { openPrefs, openSmart, toggleBrowser, newPlaylist: newList });

  function keys(e) {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) && !["checkbox", "radio", "range"].includes(document.activeElement.type);
    if (e.metaKey && e.key === ",") { e.preventDefault(); openPrefs(); return; }
    if (e.metaKey && e.key === "f") { e.preventDefault(); searchEl?.focus(); searchEl?.select(); return; }
    if (e.metaKey && e.key === "b") { e.preventDefault(); toggleBrowser(); return; }
    if (typing || prefsOpen || smartId !== undefined || dlg.current) return;
    const cur = rows.findIndex((s) => s.id === st.selected);
    const sel = (i) => { if (rows.length && st.mode !== "grid") st.selected = rows[Math.max(0, Math.min(rows.length - 1, i))].id; };
    if (e.key === " ") { e.preventDefault(); togglePlay(rows); }
    else if (e.metaKey && e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.metaKey && e.key === "ArrowLeft") { e.preventDefault(); previous(); }
    else if (e.metaKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); setVolume(st.volume + (e.key === "ArrowUp" ? 0.1 : -0.1)); }
    else if (e.key === "ArrowDown") { e.preventDefault(); sel(cur + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel(cur < 0 ? 0 : cur - 1); }
    else if (e.key === "Enter" && cur >= 0) { e.preventDefault(); play(rows[cur].id, rows.filter((r) => !r.deviceOnly).map((r) => r.id)); }
  }

  whenConnected(() => pollUpdate(true));
  $effect(() => {
    loadPrefs().catch(() => {});
    loadLibrary();
    refreshDevice(); pollSync(); pollAnalysis();
    const a = setInterval(pollAnalysis, 15000);
    const b = setInterval(() => {
      if (st.view !== "device" || (!dirty() && !playerDirty())) refreshDevice();
      if (!syncing()) pollSync(true);   // pick up a sync started anywhere (auto-sync, the menu bar)
    }, 8000);
    // pick up the background library refresh without a restart
    const c = setInterval(async () => {
      const v = await api("/api/library/version").catch(() => null);
      if (v && st.loadedAt && v.loadedAt > st.loadedAt) loadLibrary();
    }, 15000);
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); };
  });
</script>

<svelte:window onkeydown={keys} />

<div class="app">
  <TopBar bind:searchEl />
  <main>
    <Sidebar onEditSmart={openSmart} />
    {#if st.view === "device" && st.device}
      <DeviceView />
    {:else}
      <LibraryView {rows} onSignIn={() => openPrefs("general", true)} />
    {/if}
  </main>
  <StatusBar {rows} onNewSmart={() => openSmart(null)} />
</div>

{#if prefsOpen}<Preferences pane={prefsOpen.pane} startSignIn={prefsOpen.signIn} onclose={() => (prefsOpen = null)} />{/if}
{#if smartId !== undefined}<SmartEditor id={smartId} onclose={() => (smartId = undefined)} />{/if}
<Dialogs />

<style>
  .app { display: grid; grid-template-rows: auto 1fr auto; height: 100vh; }
  main { display: grid; grid-template-columns: 230px minmax(0, 1fr); min-height: 0; }
</style>
