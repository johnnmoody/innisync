<script>
  // Playback controls, the display (song, or a running sync/update), view buttons and search.
  // The round artwork with a ring tracing progress is InniSync's motif: the click wheel.
  import Icon from "./Icon.svelte";
  import Wheel from "./Wheel.svelte";
  import { st, togglePlay, previous, step, seek, setVolume, syncing, UPDATE_ACTIVE, visibleSongs, clearFilters, rebuildRecord, dismissSync, syncAllowingRemovals } from "../lib/store.svelte.js";
  import { notice, confirm } from "../lib/dialogs.svelte.js";
  import { api, art } from "../lib/api.js";
  import { MOD } from "../lib/keys.js";
  import { fmtTime } from "../lib/format.js";

  let { searchEl = $bindable() } = $props();
  let searchText = $state("");
  let t;
  function onSearch() { clearTimeout(t); t = setTimeout(() => (st.search = searchText.trim()), 200); }

  const song = $derived(st.byId[st.playing]);
  const job = $derived(
    syncing() || ["done", "error", "cancelled"].includes(st.sync.state) ? { kind: "sync", ...st.sync }
    : st.update.state !== "idle" ? { kind: "update", ...st.update } : null);
  const jobActive = $derived(job && (job.kind === "sync" ? syncing() : UPDATE_ACTIVE.includes(job.state)));
  const jobPct = $derived(!job ? 0 : job.total ? (job.done / job.total) * 100 : jobActive ? 4 : 100);
  const jobTitle = $derived(!job ? "" : !jobActive ? job.message
    : job.kind === "sync" ? `Syncing ${st.device?.name || "Y1"}` : `Updating ${st.device?.name || "Y1"}`);
  const jobSub = $derived(!job ? "" : jobActive ? (job.current ? `${job.message}: ${job.current}` : job.message)
    : job.errors?.length ? `${job.errors.length} problem${job.errors.length === 1 ? "" : "s"}: ${job.errors[0]}` : "");
  const libraryView = $derived(!["device", "mixes"].includes(st.view));
  const frac = $derived(st.duration ? st.time / st.duration : 0);
  const R = 21, C = 2 * Math.PI * R;
  const showProblems = () => notice(`${job.errors.length} problem${job.errors.length === 1 ? "" : "s"} in the last sync`,
    job.errors.join("\n") + "\n\nSongs that didn't copy are tried again next sync. Anything already on the Y1 was kept.");
  async function removeAndSync() {
    const ok = await confirm(`Remove ${job.removing.toLocaleString()} songs from the Y1?`,
      "Check that your library looks complete first: if the music server was offline or rescanning, this sync would take those songs off.",
      "Remove and Sync", true);
    if (ok) syncAllowingRemovals().catch((e) => notice("The sync didn't start", e.message));
  }
  function setMode(m) { if (st.mode !== m) clearFilters(); st.mode = m; }
</script>

<header class="bar">
  <div class="transport">
    <button class="quiet" aria-label="Previous" title="Previous ({MOD}+Left)" onclick={previous}><Icon name="prev" /></button>
    <button class="quiet play" aria-label={st.paused ? "Play" : "Pause"} title="Play or pause (Space)" onclick={() => togglePlay(visibleSongs())}><Icon name={st.paused ? "play" : "pause"} size={18} /></button>
    <button class="quiet" aria-label="Next" title="Next ({MOD}+Right)" onclick={() => step(1)}><Icon name="next" /></button>
    <label class="vol" title="Volume ({MOD}+Up / {MOD}+Down)"><span class="sr">Volume</span><Icon name="volume" size={14} />
      <input type="range" min="0" max="100" value={Math.round(st.volume * 100)} oninput={(e) => setVolume(e.currentTarget.value / 100)} /></label>
  </div>

  <div class="display" aria-live="polite">
    {#if job}
      <div class="job">
        <div class="lines"><div class="title">{jobTitle}</div><div class="sub muted">{jobSub}</div></div>
        <div class="meter" role="progressbar" aria-label={jobTitle} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(jobPct)}><div style:width="{jobPct}%"></div></div>
        {#if job.state === "error" && job.code === "manifest"}<button class="fix" onclick={() => rebuildRecord().catch((e) => notice("The record wasn't rebuilt", e.message))}>Rebuild Record</button>{/if}
        {#if job.state === "error" && job.code === "removals"}<button class="fix" onclick={removeAndSync}>Remove and Sync</button>{/if}
        {#if !jobActive && job.kind === "sync" && job.errors?.length}<button class="fix" onclick={showProblems}>Show Problems</button>{/if}
        {#if !jobActive && job.kind === "sync"}<button class="quiet x" aria-label="Dismiss" title="Dismiss" onclick={dismissSync}><Icon name="close" size={13} /></button>{/if}
        {#if jobActive && job.kind === "sync"}<button class="quiet x" aria-label="Cancel sync" title="Cancel sync" onclick={() => api("/api/sync/cancel", {})}><Icon name="close" size={13} /></button>{/if}
      </div>
    {:else if song}
      <div class="now">
        <div class="disc">
          <img src={art(song.albumId || song.id, 96)} alt="" width="40" height="40" />
          <svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r={R} class="track" /><circle cx="24" cy="24" r={R} class="done" stroke-dasharray={C} stroke-dashoffset={C * (1 - frac)} /></svg>
        </div>
        <div class="lines">
          <div class="title" title={song.name}>{song.name}</div>
          <div class="sub muted" title="{song.artist}, {song.album}">{song.artist}{song.album ? `, ${song.album}` : ""}</div>
          <div class="scrub"><span>{fmtTime(st.time)}</span>
            <input type="range" aria-label="Position in song" min="0" max="1000" value={Math.round(frac * 1000)} oninput={(e) => seek(e.currentTarget.value / 1000)} />
            <span>-{fmtTime(st.duration - st.time)}</span></div>
        </div>
      </div>
    {:else}
      <div class="idle muted"><Wheel size={22} /> InniSync</div>
    {/if}
  </div>

  <div class="right">
    {#if libraryView}
      <div class="seg" role="group" aria-label="View">
        <button class:on={st.mode === "list"} aria-pressed={st.mode === "list"} title="Songs" aria-label="Songs" onclick={() => setMode("list")}><Icon name="list" /></button>
        <button class:on={st.mode === "albums"} aria-pressed={st.mode === "albums"} title="Songs by album" aria-label="Songs by album" onclick={() => setMode("albums")}><Icon name="albums" /></button>
        <button class:on={st.mode === "grid"} aria-pressed={st.mode === "grid"} title="Covers" aria-label="Covers" onclick={() => setMode("grid")}><Icon name="grid" /></button>
      </div>
    {/if}
    <label class="search"><span class="sr">Search</span><Icon name="search" size={14} />
      <input type="search" placeholder="Search" title="Search ({MOD}+F)" bind:this={searchEl} bind:value={searchText} oninput={onSearch} /></label>
  </div>
</header>

<style>
  .bar { display: grid; grid-template-columns: 1fr minmax(320px, 520px) 1fr; align-items: center; gap: 16px; height: 64px; padding: 0 14px; border-bottom: 1px solid var(--line); background: var(--surface); }
  .transport { display: flex; align-items: center; gap: 2px; }
  .transport button { padding: 6px 8px; }
  .play { padding: 6px 10px; }
  .vol { display: flex; align-items: center; gap: 6px; margin-left: 10px; color: var(--text-2); }
  .vol input { width: 96px; accent-color: var(--accent); }
  .display { height: 50px; border: 1px solid var(--line); border-radius: var(--r-md); background: var(--bg); display: flex; align-items: center; padding: 0 12px; min-width: 0; }
  .now, .job { display: flex; align-items: center; gap: 12px; width: 100%; min-width: 0; }
  .lines { flex: 1; min-width: 0; }
  .title { font-weight: 700; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .disc { position: relative; width: 48px; height: 48px; flex: none; }
  .disc img { position: absolute; inset: 4px; border-radius: 50%; object-fit: cover; background: var(--line); }
  .disc svg { position: absolute; inset: 0; transform: rotate(-90deg); }
  .disc circle { fill: none; stroke-width: 2.5; }
  .track { stroke: var(--line); }
  .done { stroke: var(--accent); stroke-linecap: round; }
  .scrub { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .scrub input { flex: 1; height: 12px; accent-color: var(--accent); }
  .meter { width: 120px; height: 6px; border-radius: 3px; background: var(--line); overflow: hidden; flex: none; }
  .meter div { height: 100%; background: var(--accent); }
  .x { padding: 4px 6px; min-height: 24px; }
  .fix { flex: none; min-height: 26px; padding: 2px 10px; font-size: 12px; }
  .idle { display: flex; align-items: center; gap: 8px; margin: 0 auto; font-weight: 600; }
  .right { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
  .seg { display: flex; border: 1px solid var(--line-strong); border-radius: var(--r-sm); overflow: hidden; }
  .seg button { border: 0; border-radius: 0; padding: 4px 9px; background: var(--surface); color: var(--text-2); }
  .seg button + button { border-left: 1px solid var(--line-strong); }
  .seg button.on { background: var(--accent-soft); color: var(--text); }
  .search { display: flex; align-items: center; gap: 6px; border: 1px solid var(--line-strong); border-radius: var(--r-sm); padding: 0 8px; background: var(--surface); color: var(--text-2); }
  .search input { border: 0; padding: 4px 0; width: 170px; background: none; color: var(--text); outline: none; }
  .search:focus-within { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
