<script>
  // What music syncs: everything, or chosen playlists, artists and genres; plus mixes.
  import Icon from "../Icon.svelte";
  import { st } from "../../lib/store.svelte.js";
  const s = $derived(st.settings);
  const counts = (f) => { const m = {}; for (const x of st.songs) for (const v of f(x)) m[v] = (m[v] || 0) + 1; return Object.entries(m).sort((a, b) => a[0].localeCompare(b[0])); };
  const artists = $derived(counts((x) => [x.albumArtist || x.artist || "Unknown Artist"]));
  const genres = $derived(counts((x) => x.genres));
  const off = $derived(!s.sync_music || s.mode === "all");
  function toggle(key, v, on) { const arr = s[key].filter((x) => x !== v); if (on) arr.push(v); s[key] = arr; }
</script>

<div class="wide head">
  <label class="big"><input type="checkbox" bind:checked={s.sync_music} /> Sync music</label>
  {#if st.plan}<span class="muted">{st.plan.fits ? `${st.plan.songs_after.toLocaleString()} songs on the Y1 after syncing` : ""}</span>{/if}
</div>
<div class="card">
  <label><input type="radio" bind:group={s.mode} value="all" disabled={!s.sync_music} /> Your whole library</label>
  <label><input type="radio" bind:group={s.mode} value="selected" disabled={!s.sync_music} /> Chosen playlists, artists and genres</label>
  <label class="sub"><input type="checkbox" bind:checked={s.fill_free} disabled={!s.sync_music} /> Fill the free space with more songs</label>
  <label title="Mixes are rebuilt on every sync from how your songs sound"><input type="checkbox" bind:checked={s.sync_mixes} /> Sync mixes</label>
</div>
<div class="wide lists" class:off>
  <section>
    <h3>Playlists</h3>
    <div class="list">
      {#each st.playlists as p (p.id)}
        <label><input type="checkbox" disabled={off} checked={s.playlists.includes(p.id)} onchange={(e) => toggle("playlists", p.id, e.currentTarget.checked)} /><Icon name={p.smart ? "smart" : "playlist"} size={14} /><span class="t">{p.name}</span><span class="n">{(st.plItems[p.id] || []).length}</span></label>
      {:else}<p class="muted">No playlists</p>{/each}
    </div>
  </section>
  <section>
    <h3>Artists</h3>
    <div class="list">
      {#each artists as [v, n] (v)}
        <label><input type="checkbox" disabled={off} checked={s.artists.includes(v)} onchange={(e) => toggle("artists", v, e.currentTarget.checked)} /><span class="t">{v}</span><span class="n">{n}</span></label>
      {/each}
    </div>
  </section>
  <section>
    <h3>Genres</h3>
    <div class="list">
      {#each genres as [v, n] (v)}
        <label><input type="checkbox" disabled={off} checked={s.genres.includes(v)} onchange={(e) => toggle("genres", v, e.currentTarget.checked)} /><span class="t">{v}</span><span class="n">{n}</span></label>
      {/each}
    </div>
  </section>
</div>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; }
  .big { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; }
  .card label { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
  .card label.sub { margin-left: 24px; }
  .lists { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
  .lists.off { opacity: 0.5; }
  h3 { font-size: 12px; color: var(--text-2); margin: 0 0 6px; font-weight: 600; }
  .list { height: 300px; overflow-y: auto; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 4px 0; }
  .list label { display: flex; align-items: center; gap: 7px; padding: 3px 10px; font-size: 13px; }
  .list label:hover { background: var(--hover); }
  .list :global(svg) { color: var(--text-2); flex: none; }
  .t { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .n { color: var(--text-2); font-size: 11px; font-variant-numeric: tabular-nums; }
  .list p { padding: 4px 10px; margin: 0; font-size: 13px; }
</style>
