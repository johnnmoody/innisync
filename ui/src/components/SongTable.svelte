<script>
  // The song list. Only the rows in view are drawn (the library can be thousands of songs).
  // In "Songs by album" mode each album gets a heading row with its cover.
  import { st, play, albumGroups } from "../lib/store.svelte.js";
  import { art } from "../lib/api.js";
  import { fmtTime } from "../lib/format.js";

  let { rows } = $props();
  const ROW = 28, HEAD = 56;
  let box = $state(), scrollTop = $state(0), height = $state(600);

  // flatten into drawable lines: {kind: "head"|"song", h, top, ...}
  const lines = $derived.by(() => {
    const out = [];
    let top = 0;
    if (st.mode === "albums") {
      for (const g of albumGroups(rows)) {
        out.push({ kind: "head", g, top, h: HEAD }); top += HEAD;
        g.items.forEach((s, i) => { out.push({ kind: "song", s, top, h: ROW, odd: i % 2 === 1 }); top += ROW; });
      }
    } else rows.forEach((s, i) => { out.push({ kind: "song", s, top, h: ROW, odd: i % 2 === 1 }); top += ROW; });
    return { out, total: top };
  });
  const view = $derived.by(() => {
    const L = lines.out, lo = scrollTop - 200, hi = scrollTop + height + 200;
    let a = 0, b = L.length;
    while (a < b) { const m = (a + b) >> 1; if (L[m].top + L[m].h < lo) a = m + 1; else b = m; }
    const start = a;
    let end = start;
    while (end < L.length && L[end].top < hi) end++;
    return L.slice(start, end);
  });
  const queue = $derived(rows.filter((r) => !r.deviceOnly).map((r) => r.id));
  const ownOrder = $derived(["playlist", "devpl", "similar"].includes(st.view));

  // keep the selected row in view when the keyboard moves the selection
  $effect(() => {
    const id = st.selected;
    if (!box || !id) return;
    const line = lines.out.find((l) => l.kind === "song" && l.s.id === id);
    if (!line) return;
    if (line.top < box.scrollTop) box.scrollTop = line.top;
    else if (line.top + ROW > box.scrollTop + box.clientHeight) box.scrollTop = line.top + ROW - box.clientHeight;
  });

  const COLS = [["name", "Name"], ["duration", "Time"], ["artist", "Artist"], ["album", "Album"], ["genre", "Genre"], ["container", "Kind"]];
  function sortBy(k) { st.sort = { key: k, dir: st.sort.key === k ? -st.sort.dir : 1 }; }
  const kind = (s) => (s.container || "").toUpperCase();
</script>

<div class="table" role="table" aria-label="Songs" aria-rowcount={rows.length}>
  <div class="thead" role="row">
    {#each COLS as [k, label]}
      <div role="columnheader" class="c-{k}" aria-sort={!ownOrder && st.sort.key === k ? (st.sort.dir > 0 ? "ascending" : "descending") : "none"}>
        {#if ownOrder}<span>{label}</span>
        {:else}<button class:on={st.sort.key === k} onclick={() => sortBy(k)}>{label}{#if st.sort.key === k}<span class="arrow" aria-hidden="true">{st.sort.dir > 0 ? "▲" : "▼"}</span>{/if}</button>{/if}
      </div>
    {/each}
  </div>
  <div class="scroll" bind:this={box} bind:clientHeight={height} onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}>
    <div class="spacer" style:height="{lines.total}px">
      {#each view as l (l.kind === "head" ? "h" + l.g.key : l.s.id)}
        {#if l.kind === "head"}
          <div class="head" style:top="{l.top}px" role="row">
            <img src={art(l.g.art, 96)} alt="" width="40" height="40" loading="lazy" />
            <div><div class="album">{l.g.album}</div><div class="muted">{l.g.artist}{l.g.year ? ` · ${l.g.year}` : ""}</div></div>
          </div>
        {:else}
          {@const s = l.s}
          <div class="row" role="row" style:top="{l.top}px" class:odd={l.odd} class:sel={st.selected === s.id} class:playing={st.playing === s.id} class:dim={s.deviceOnly}
            aria-selected={st.selected === s.id} tabindex="-1" onclick={() => (st.selected = s.id)} ondblclick={() => play(s.id, queue)} onkeydown={(e) => e.key === "Enter" && play(s.id, queue)}
            title={s.deviceOnly ? "Only on the Y1 (added outside InniSync), so it can't play here" : ""}>
            <div role="cell" class="c-name">{#if st.playing === s.id}<span class="dot" aria-label="Playing"></span>{/if}<span class="t">{s.name}</span></div>
            <div role="cell" class="c-duration">{s.duration ? fmtTime(s.duration) : ""}</div>
            <div role="cell" class="c-artist" title={s.artist}>{s.artist}</div>
            <div role="cell" class="c-album" title={s.album}>{s.album}</div>
            <div role="cell" class="c-genre" title={s.genres.join(", ")}>{s.genres[0] || ""}</div>
            <div role="cell" class="c-container" title="{kind(s)}{s.bitrate ? `, ${Math.round(s.bitrate / 1000)} kbps` : ''}">{kind(s)}</div>
          </div>
        {/if}
      {/each}
    </div>
  </div>
</div>

<style>
  .table { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  .thead, .row { display: grid; grid-template-columns: minmax(180px, 3fr) 64px minmax(120px, 2fr) minmax(120px, 2fr) minmax(80px, 1fr) 64px; align-items: center; }
  .thead { border-bottom: 1px solid var(--line); background: var(--surface); font-size: 12px; color: var(--text-2); }
  .thead > div { padding: 0 10px; height: 30px; display: flex; align-items: center; }
  .thead button { border: 0; background: none; padding: 0; min-height: 0; font-weight: 600; color: var(--text-2); display: flex; gap: 4px; align-items: center; }
  .thead button.on { color: var(--text); }
  .arrow { font-size: 8px; }
  .scroll { flex: 1; overflow-y: auto; overflow-x: hidden; background: var(--surface); }
  .spacer { position: relative; }
  .row, .head { position: absolute; left: 0; right: 0; }
  .row { height: 28px; font-size: 13px; outline: none; }
  .row.odd { background: var(--stripe); }
  .row:hover { background: var(--hover); }
  .row.sel { background: var(--accent-soft); }
  .row.dim { color: var(--text-2); }
  .row > div { padding: 0 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .c-name { display: flex; align-items: center; gap: 6px; }
  .c-name .t { overflow: hidden; text-overflow: ellipsis; }
  .c-duration { font-variant-numeric: tabular-nums; color: var(--text-2); }
  .c-container { color: var(--text-2); font-size: 12px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex: none; }
  .row.playing .t { font-weight: 700; }
  .head { height: 56px; display: flex; align-items: center; gap: 12px; padding: 0 10px; border-top: 1px solid var(--line); }
  .head img { border-radius: var(--r-sm); object-fit: cover; background: var(--line); }
  .album { font-weight: 700; }
  .head .muted { font-size: 12px; }
</style>
