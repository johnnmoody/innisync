<script>
  // Mixes: groups of songs on the Y1 that sound alike, worked out on this computer. Double-click to play one.
  import { st, play } from "../lib/store.svelte.js";
  import { art } from "../lib/api.js";
  let sel = $state(null);
  function covers(m) {
    const out = [];
    for (const id of m.items) { const s = st.byId[id], a = s && (s.albumId || s.id); if (a && !out.includes(a)) out.push(a); if (out.length === 4) break; }
    return out;
  }
  function start(m) { const ids = m.items.filter((id) => st.byId[id]); if (ids.length) play(ids[0], ids); }
  const a = $derived(st.analysis || {});
</script>

<div class="wrap">
  {#if st.mixes === null}
    <p class="note muted">Working out your mixes…</p>
  {:else if !st.mixes.length}
    <p class="note muted">{a.state === "analyzing"
      ? `InniSync is listening to the songs on your Y1 (${a.done} of ${a.total}). Mixes appear when it's done.`
      : "Mixes need at least 40 analysed songs on your Y1. Sync some music first."}</p>
  {:else}
    <div class="grid">
      {#each st.mixes as m, n (m.name)}
        <button class="cell" class:sel={sel === n} title="{m.name}: {m.items.length} songs. Double-click to play." onclick={() => (sel = n)} ondblclick={() => start(m)}>
          <span class="mosaic">{#each covers(m) as c}<img src={art(c, 150)} alt="" width="80" height="80" loading="lazy" />{/each}</span>
          <span class="t1">{m.name}</span><span class="t2 muted">{m.artists.join(", ")}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .wrap { flex: 1; overflow-y: auto; background: var(--surface); }
  .note { max-width: 460px; margin: 64px auto; text-align: center; }
  .grid { padding: 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 18px 16px; }
  .cell { display: flex; flex-direction: column; gap: 2px; border: 0; background: none; padding: 6px; border-radius: var(--r-md); text-align: left; min-width: 0; }
  .cell:hover { background: var(--hover); }
  .cell.sel { background: var(--accent-soft); }
  .mosaic { display: grid; grid-template-columns: 1fr 1fr; aspect-ratio: 1; border-radius: var(--r-sm); overflow: hidden; background: var(--line); margin-bottom: 6px; }
  .mosaic img { width: 100%; height: 100%; object-fit: cover; }
  .t1 { font-weight: 600; font-size: 13px; }
  .t2 { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
