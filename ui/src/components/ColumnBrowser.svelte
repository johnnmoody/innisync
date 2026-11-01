<script>
  import { st, browserColumns } from "../lib/store.svelte.js";
  const cols = $derived(browserColumns());
  function pick(k, v) {
    st[k] = v;
    if (k === "genre") st.artist = st.album = null;
    if (k === "artist") st.album = null;
  }
  const label = (n, one, many) => `All (${n.toLocaleString()} ${n === 1 ? one : many})`;
</script>

<div class="browser">
  {#each [["genre", "Genres", cols.genres, "genre", "genres"], ["artist", "Artists", cols.artists, "artist", "artists"], ["album", "Albums", cols.albums, "album", "albums"]] as [k, title, items, one, many]}
    <div class="col">
      <div class="h">{title}</div>
      <div class="list" role="listbox" aria-label={title}>
        <button role="option" aria-selected={!st[k]} class:sel={!st[k]} onclick={() => pick(k, null)}>{label(items.length, one, many)}</button>
        {#each items as v}<button role="option" aria-selected={st[k] === v} class:sel={st[k] === v} title={v} onclick={() => pick(k, v)}>{v}</button>{/each}
      </div>
    </div>
  {/each}
</div>

<style>
  .browser { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); height: 180px; border-bottom: 1px solid var(--line); flex: none; }
  .col { display: flex; flex-direction: column; min-width: 0; }
  .col + .col { border-left: 1px solid var(--line); }
  .h { font-size: 12px; font-weight: 600; color: var(--text-2); padding: 6px 10px; border-bottom: 1px solid var(--line); background: var(--surface); }
  .list { overflow-y: auto; background: var(--surface); flex: 1; }
  .list button { display: block; width: 100%; text-align: left; border: 0; border-radius: 0; background: none; min-height: 24px; padding: 2px 10px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .list button:hover { background: var(--hover); }
  .list button.sel { background: var(--accent-soft); }
</style>
