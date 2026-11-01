<script>
  import Icon from "./Icon.svelte";
  import { st, toggleBrowser, openSimilar, newPlaylist } from "../lib/store.svelte.js";
  import { fmtSpan, fmtSize, plural } from "../lib/format.js";
  import { askText, notice } from "../lib/dialogs.svelte.js";
  let { rows, onNewSmart } = $props();

  const summary = $derived.by(() => {
    if (st.view === "device") return "";
    if (st.view === "mixes") return st.mixes?.length ? `${plural(st.mixes.length, "mix", "mixes")} from ${st.analysis?.analyzed ?? "the"} songs on your Y1` : "";
    const secs = rows.reduce((t, s) => t + (s.duration || 0), 0), bytes = rows.reduce((t, s) => t + (s.size || 0), 0);
    return `${plural(rows.length, "song")}, ${fmtSpan(secs)}, ${fmtSize(bytes)}`;
  });
  // a message (an error, "added to the Y1", ...) replaces the summary for a few seconds
  let shown = $state("");
  $effect(() => { const m = st.status; if (!m) return; shown = m; const t = setTimeout(() => { shown = ""; st.status = ""; }, 6000); return () => clearTimeout(t); });
  const analysing = $derived(st.analysis?.state === "analyzing" ? `Listening to your Y1's songs: ${st.analysis.done} of ${st.analysis.total}` : "");

  async function newList(e) {
    if (e.altKey) return onNewSmart();
    const name = await askText("New Playlist", "", "untitled playlist", "Create");
    if (!name) return;
    try { await newPlaylist(name); } catch (err) { notice("The playlist wasn't created", err.message); }
  }
  const browserAllowed = $derived(st.mode !== "grid" && !["device", "mixes", "playlist", "similar", "devpl"].includes(st.view));
</script>

<footer class="status">
  <div class="left">
    <button class="quiet" title="New playlist (Option-click for a smart playlist)" aria-label="New playlist" onclick={newList}><Icon name="plus" size={14} /></button>
    <button class="quiet" class:on={st.shuffle} aria-pressed={st.shuffle} title="Shuffle" aria-label="Shuffle" onclick={() => (st.shuffle = !st.shuffle)}><Icon name="shuffle" size={14} /></button>
    <button class="quiet" class:on={st.repeat} aria-pressed={st.repeat} title="Repeat" aria-label="Repeat" onclick={() => (st.repeat = !st.repeat)}><Icon name="repeat" size={14} /></button>
    <button class="quiet" class:on={st.showBrowser} aria-pressed={st.showBrowser} disabled={!browserAllowed} title="{st.showBrowser ? 'Hide' : 'Show'} column browser (Cmd+B)" aria-label="Column browser" onclick={() => toggleBrowser()}><Icon name="columns" size={14} /></button>
  </div>
  <div class="mid" aria-live="polite">{shown || summary}</div>
  <div class="right">
    {#if analysing}<span class="muted small">{analysing}</span>{/if}
    <button title="Songs on your Y1 that go with the selected song" onclick={() => openSimilar(st.selected || st.playing)}><Icon name="similar" size={14} /> Similar Songs</button>
  </div>
</footer>

<style>
  .status { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; height: 38px; padding: 0 10px; border-top: 1px solid var(--line); background: var(--surface); font-size: 12px; }
  .left { display: flex; gap: 2px; }
  .left button { padding: 4px 7px; min-height: 26px; color: var(--text-2); }
  .left button.on { background: var(--accent-soft); color: var(--text); }
  .mid { color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .right { display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
  .right button { display: flex; gap: 6px; align-items: center; min-height: 26px; padding: 2px 10px; font-size: 12px; }
  .small { font-size: 12px; }
</style>
