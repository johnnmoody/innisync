<script>
  // How the Y1's space is used, previewing what the next sync would change, with Revert / Apply / Sync.
  // On the Settings tab those buttons act on the player's settings instead of on what syncs.
  import { st, dirty, playerDirty, startSync, syncing, rebuildRecord } from "../../lib/store.svelte.js";
  import { api } from "../../lib/api.js";
  import { fmtSize } from "../../lib/format.js";
  import { notice, confirm } from "../../lib/dialogs.svelte.js";

  const d = $derived(st.device);
  const parts = $derived.by(() => {
    const delta = st.plan ? st.plan.add_bytes - st.plan.remove_bytes : 0;
    return [["Audio", Math.max(d.audio + delta, 0), "var(--accent)"], ["Video", d.video, "var(--text-2)"],
      ["Photos", d.photos, "color-mix(in srgb, var(--accent) 45%, var(--surface))"], ["Other", d.other, "var(--line-strong)"],
      ["Free", Math.max(d.free - delta, 0), "transparent"]];
  });
  const onSettings = $derived(st.tab === "settings");
  const changed = $derived(onSettings ? playerDirty() : dirty());
  let busy = $state(false);

  function revert() {
    if (onSettings) st.player = structuredClone($state.snapshot(st.playerSaved));
    else st.settings = structuredClone($state.snapshot(st.saved));
  }
  async function apply() {
    busy = true;
    try {
      if (onSettings) { await api("/api/device/player", { settings: $state.snapshot(st.player) }); st.playerSaved = structuredClone($state.snapshot(st.player)); }
      else if (st.plan && !st.plan.fits) await notice("Not enough space on the Y1", "Choose fewer songs, or turn on “Convert lossless songs to 320 kbps MP3” on the Summary page.");
      else await startSync();
    } catch (e) {
      if (e.code === "manifest" && await confirm("Rebuild the Y1's record?", `${e.message}\n\nInniSync can rebuild it from the songs already on the Y1. Files it doesn't recognise are left alone.`, "Rebuild Record")) {
        try { const r = await rebuildRecord(); await notice("Record rebuilt", `Found ${r.songs} songs and ${r.playlists} playlists on the Y1. You can sync now.`); }
        catch (er) { await notice("The record wasn't rebuilt", er.message); }
      } else if (e.code !== "manifest") await notice(onSettings ? "The settings weren't saved" : "The sync didn't start", e.message);
    }
    busy = false;
  }
</script>

<footer class="cap">
  <div class="bar" role="img" aria-label="Storage: {parts.map(([n, b]) => `${n} ${fmtSize(b)}`).join(', ')}">
    {#each parts as [n, b, c]}<span title="{n}: {fmtSize(b)}" style:width="{Math.max((b / (d.capacity || 1)) * 100, b > 0 ? 0.4 : 0)}%" style:background={c}></span>{/each}
  </div>
  <div class="legend">
    {#each parts as [n, b, c]}<span><i style:background={c} class:free={n === "Free"}></i>{n} <b>{fmtSize(b)}</b></span>{/each}
    <span class="total muted">of {fmtSize(d.capacity)}</span>
    {#if st.plan && !st.plan.fits && !onSettings}<span class="err">Not enough space: {fmtSize(st.plan.add_bytes - st.plan.budget)} over</span>{/if}
  </div>
  <div class="btns">
    {#if changed}<button onclick={revert}>Revert</button>{/if}
    <button class="primary" disabled={busy || (onSettings && !changed) || (!onSettings && syncing())} onclick={apply}>{changed || onSettings ? "Apply" : "Sync"}</button>
  </div>
</footer>

<style>
  .cap { display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto; gap: 6px 16px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line); background: var(--surface); flex: none; }
  .bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; border: 1px solid var(--line-strong); background: var(--bg); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--text-2); grid-column: 1; }
  .legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
  .legend i.free { border: 1px solid var(--line-strong); }
  .legend b { color: var(--text); font-weight: 600; }
  .btns { grid-column: 2; grid-row: 1 / 3; display: flex; gap: 8px; }
  .btns button { min-width: 84px; }
</style>
