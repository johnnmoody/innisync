<script>
  // Covers of albums, artists or genres. Double-click an album to play it; an artist or genre opens its albums.
  import { st, gridGroups, play } from "../lib/store.svelte.js";
  import { art } from "../lib/api.js";
  let { rows } = $props();
  let sel = $state(null);
  const groups = $derived(gridGroups(rows));
  function open(g) {
    st.genre = g.filter.genre ?? st.genre;
    st.artist = g.filter.artist ?? (g.filter.genre ? null : st.artist);
    st.album = g.filter.album ?? null;
    if (st.gridBy === "albums") {
      st.mode = "list";
      const ids = g.items.filter((s) => !s.deviceOnly).map((s) => s.id);
      if (ids.length) play(ids[0], ids);
    } else st.gridBy = "albums";
  }
</script>

<div class="by" role="group" aria-label="Group covers by">
  {#each [["albums", "Albums"], ["artists", "Artists"], ["genres", "Genres"]] as [k, label]}
    <button class:on={st.gridBy === k} aria-pressed={st.gridBy === k} onclick={() => (st.gridBy = k)}>{label}</button>
  {/each}
</div>
<div class="grid">
  {#each groups as g (g.key)}
    <button class="cell" class:sel={sel === g.key} title="{g.title}{g.sub ? `, ${g.sub}` : ''} ({g.items.length} {g.items.length === 1 ? 'song' : 'songs'})"
      onclick={() => (sel = g.key)} ondblclick={() => open(g)}>
      <img src={art(g.art, 280)} alt="" width="160" height="160" loading="lazy" />
      <span class="t1">{g.title}</span><span class="t2 muted">{g.sub}</span>
    </button>
  {:else}
    <p class="muted none">No songs match.</p>
  {/each}
</div>

<style>
  .by { display: flex; gap: 6px; padding: 8px 14px; border-bottom: 1px solid var(--line); background: var(--surface); flex: none; }
  .by button { min-height: 24px; padding: 2px 10px; font-size: 13px; }
  .by button.on { background: var(--accent-soft); border-color: transparent; }
  .grid { flex: 1; overflow-y: auto; padding: 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 18px 16px; align-content: start; background: var(--surface); }
  .cell { display: flex; flex-direction: column; gap: 2px; border: 0; background: none; padding: 6px; border-radius: var(--r-md); text-align: left; min-width: 0; }
  .cell:hover { background: var(--hover); }
  .cell.sel { background: var(--accent-soft); }
  img { width: 100%; height: auto; aspect-ratio: 1; object-fit: cover; border-radius: var(--r-sm); background: var(--line); margin-bottom: 6px; }
  .t1 { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t2 { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .none { grid-column: 1 / -1; }
</style>
