<script>
  import Icon from "./Icon.svelte";
  import { st, go, loadDeviceContents, openSimilar, loadLibrary } from "../lib/store.svelte.js";
  import { y1Svg } from "../lib/y1.js";
  import { api } from "../lib/api.js";
  import { confirm } from "../lib/dialogs.svelte.js";

  let { onEditSmart } = $props();
  let menu = $state(null);   // {x, y, playlist}

  const isSel = (view, extra) => st.view === view && (extra === undefined || extra);
  function toggleDevice(e) {
    e.stopPropagation();
    st.devOpen = !st.devOpen;
    if (st.devOpen && !st.dev) loadDeviceContents();
  }
  function openWanted() { window.open(st.prefs.lidarr_url.replace(/\/$/, "") + "/wanted/missing"); }
  function context(e, p) {
    if (!p.smart) return;
    e.preventDefault();
    menu = { x: e.clientX, y: e.clientY, playlist: p };
  }
  async function del(p) {
    menu = null;
    if (!(await confirm(`Delete “${p.name}”?`, "Songs aren't deleted. The next sync removes this playlist from the Y1.", "Delete", true))) return;
    await api("/api/smart/delete", { id: p.id });
    if (st.playlist === p.id) go("music");
    await loadLibrary();
  }
  $effect(() => {
    if (!menu) return;
    const close = (e) => { if (e.type === "keydown" && e.key !== "Escape") return; menu = null; };
    setTimeout(() => { addEventListener("mousedown", close); addEventListener("keydown", close); });
    return () => { removeEventListener("mousedown", close); removeEventListener("keydown", close); };
  });
</script>

<nav class="side" aria-label="Library and devices">
  <h3>Library</h3>
  <button class="item" class:sel={isSel("music")} onclick={() => go("music")}><Icon name="music" />Music</button>
  <button class="item" class:sel={isSel("recent")} onclick={() => go("recent")}><Icon name="recent" />Recently Added</button>
  {#if st.prefs?.lidarr_url}<button class="item" onclick={openWanted} title="Opens Lidarr's missing albums"><Icon name="wanted" />Wanted</button>{/if}

  <h3>Y1</h3>
  {#if st.device}
    <div class="devrow" class:sel={isSel("device")}>
      <button class="disc" class:open={st.devOpen} aria-label={st.devOpen ? "Hide what's on the Y1" : "Show what's on the Y1"} aria-expanded={st.devOpen} onclick={toggleDevice}><Icon name="chevron" size={12} /></button>
      <button class="item dev" onclick={() => go("device")}><span class="y1" aria-hidden="true">{@html y1Svg(st.y1Color)}</span><span class="name">{st.device.name}</span>
        {#if st.device.battery != null}<span class="batt muted" title="Battery">{st.device.battery}%</span>{/if}</button>
    </div>
    {#if st.devOpen}
      <div class="kids">
        {#if !st.dev}<div class="empty muted">Reading the Y1…</div>
        {:else}
          <button class="item" class:sel={isSel("devmusic")} title="{st.dev.songs.length} songs on the Y1" onclick={() => go("devmusic")}><Icon name="music" />Music</button>
          {#each st.dev.playlists as p (p.id)}
            <button class="item" class:sel={isSel("devpl", st.devPl === p.id)} title="{p.name} ({p.items.length} songs on the Y1)" onclick={() => go("devpl", { devPl: p.id })}><Icon name="playlist" /><span class="name">{p.name}</span></button>
          {/each}
        {/if}
      </div>
    {/if}
  {:else}
    <div class="empty muted">Connect your Y1 by USB</div>
  {/if}

  <h3>Mixes</h3>
  <button class="item" class:sel={isSel("mixes")} title="Mixes of songs on your Y1 that sound alike" onclick={() => go("mixes")}><Icon name="mix" />Mixes</button>
  {#each st.keptSeeds.filter((id) => st.byId[id]) as id (id)}
    <button class="item" class:sel={isSel("similar", st.similar.seed === id)} title="Songs like {st.byId[id].name} (kept on the Y1)" onclick={() => openSimilar(id)}><Icon name="similar" /><span class="name">{st.byId[id].name}</span></button>
  {/each}

  <h3>Playlists</h3>
  {#each st.playlists as p (p.id)}
    <button class="item" class:sel={isSel("playlist", st.playlist === p.id)} title="{p.name} ({(st.plItems[p.id] || []).length} songs)"
      onclick={() => go("playlist", { playlist: p.id })} oncontextmenu={(e) => context(e, p)}><Icon name={p.smart ? "smart" : "playlist"} /><span class="name">{p.name}</span></button>
  {:else}
    <div class="empty muted">{st.signedOut ? "Sign in to see your playlists" : "No playlists yet"}</div>
  {/each}
</nav>

{#if menu}
  <div class="menu" role="menu" style:left="{menu.x}px" style:top="{menu.y}px">
    <button role="menuitem" onmousedown={(e) => e.stopPropagation()} onclick={() => { const p = menu.playlist; menu = null; onEditSmart(p.id); }}>Edit Smart Playlist…</button>
    <button role="menuitem" onmousedown={(e) => e.stopPropagation()} onclick={() => del(menu.playlist)}>Delete</button>
  </div>
{/if}

<style>
  .side { background: var(--sidebar); border-right: 1px solid var(--line); overflow-y: auto; padding: 8px 8px 16px; }
  h3 { font-size: 11px; font-weight: 700; color: var(--text-2); margin: 14px 8px 4px; }
  h3:first-child { margin-top: 4px; }
  .item { display: flex; align-items: center; gap: 8px; width: 100%; border: 0; background: none; border-radius: var(--r-sm); padding: 4px 8px; min-height: 28px; text-align: left; color: var(--text); }
  .item :global(svg) { flex: none; color: var(--text-2); }
  .item:hover { background: var(--hover); }
  .item.sel, .devrow.sel { background: var(--accent-soft); }
  .item.sel :global(svg) { color: var(--text); }
  .name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .devrow { display: flex; align-items: center; border-radius: var(--r-sm); }
  .devrow .item.dev { padding-left: 2px; }
  .devrow .item.dev:hover, .devrow.sel .item.dev { background: none; }
  .disc { border: 0; background: none; padding: 0 2px; min-height: 28px; color: var(--text-2); }
  .disc :global(svg) { transition: transform 0.12s; }
  .disc.open :global(svg) { transform: rotate(90deg); }
  .y1 { width: 12px; height: 19px; flex: none; display: flex; }
  .y1 :global(svg) { width: 100%; height: 100%; }
  .batt { font-size: 12px; font-variant-numeric: tabular-nums; }
  .kids { margin-left: 16px; }
  .empty { padding: 4px 8px; font-size: 13px; }
  .menu { position: fixed; z-index: 60; min-width: 190px; padding: 4px; background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--r-md); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2); }
  .menu button { display: block; width: 100%; text-align: left; border: 0; background: none; border-radius: var(--r-sm); }
  .menu button:hover { background: var(--accent); color: var(--on-accent); }
</style>
