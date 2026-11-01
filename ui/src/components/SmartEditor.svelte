<script>
  // A playlist made from rules ("match all/any of"), with an optional limit. The server works out the songs.
  import Modal from "./Modal.svelte";
  import Icon from "./Icon.svelte";
  import { st, loadLibrary, go } from "../lib/store.svelte.js";
  import { api } from "../lib/api.js";
  import { fmtSpan, fmtSize } from "../lib/format.js";

  let { id = null, onclose } = $props();
  let meta = $state(null), d = $state(null), preview = $state(""), previewErr = $state(false), err = $state("");
  $effect(() => {
    api("/api/smart").then((m) => {
      meta = m;
      const found = m.playlists.find((p) => p.id === id);
      d = found ? structuredClone(found) : { name: "untitled smart playlist", match: "all", rules: [{ field: "artist", op: "contains", value: "" }], limit: { on: false, count: 25, unit: "songs", by: "random" } };
    });
  });
  let t;
  $effect(() => {
    if (!d) return;
    const body = $state.snapshot(d);
    clearTimeout(t);
    t = setTimeout(async () => {
      try { const p = await api("/api/smart/preview", body); preview = `${p.count.toLocaleString()} songs, ${fmtSpan(p.seconds)}, ${fmtSize(p.bytes)}`; previewErr = false; }
      catch (e) { preview = e.message; previewErr = true; }
    }, 250);
  });
  const kindOf = (r) => meta.fields[r.field][1];
  function fieldChanged(r) {
    const k = kindOf(r);
    if (!meta.ops[k].includes(r.op)) r.op = meta.ops[k][0];
    r.value = k === "date" ? 2 : ""; delete r.value2; r.unit = "weeks";
  }
  function opChanged(r) { if (kindOf(r) === "date") r.value = /last/.test(r.op) ? 2 : ""; }
  async function save() {
    try {
      const saved = await api("/api/smart/save", $state.snapshot(d));
      onclose(); await loadLibrary(); go("playlist", { playlist: saved.id });
    } catch (e) { err = e.message; }
  }
</script>

<Modal title={id ? `Edit ${d?.name ?? "smart playlist"}` : "New Smart Playlist"} {onclose} width={700}>
  {#if !d}
    <p class="muted">Loading…</p>
  {:else}
    <div class="line">Match
      <select aria-label="Match all or any" bind:value={d.match}><option value="all">all</option><option value="any">any</option></select>
      of these rules:</div>
    <div class="rules">
      {#each d.rules as r, i}
        <div class="rule">
          <select aria-label="Field" bind:value={r.field} onchange={() => fieldChanged(r)}>
            {#each Object.entries(meta.fields) as [k, [label]]}<option value={k}>{label}</option>{/each}
          </select>
          <select aria-label="Condition" bind:value={r.op} onchange={() => opChanged(r)}>
            {#each meta.ops[kindOf(r)] as op}<option>{op}</option>{/each}
          </select>
          {#if kindOf(r) === "text"}<input type="text" aria-label="Value" bind:value={r.value} />
          {:else if kindOf(r) === "number"}<input type="number" aria-label="Value" bind:value={r.value} />{#if r.op === "is in the range"} to <input type="number" aria-label="Upper value" bind:value={r.value2} />{/if}
          {:else if kindOf(r) === "date"}
            {#if /last/.test(r.op)}<input type="number" min="1" aria-label="How many" bind:value={r.value} /><select aria-label="Unit" bind:value={r.unit}><option>days</option><option>weeks</option><option>months</option></select>
            {:else}<input type="date" aria-label="Date" bind:value={r.value} />{/if}
          {/if}
          <span class="sp"></span>
          <button class="quiet" aria-label="Remove this rule" disabled={d.rules.length < 2} onclick={() => d.rules.splice(i, 1)}>–</button>
          <button class="quiet" aria-label="Add a rule after this one" onclick={() => d.rules.splice(i + 1, 0, { field: "artist", op: "contains", value: "" })}><Icon name="plus" size={12} /></button>
        </div>
      {/each}
    </div>
    <div class="line">
      <label class="chk"><input type="checkbox" bind:checked={d.limit.on} /> Limit to</label>
      <input class="num" type="number" min="1" aria-label="Limit amount" disabled={!d.limit.on} bind:value={d.limit.count} />
      <select aria-label="Limit unit" disabled={!d.limit.on} bind:value={d.limit.unit}>{#each meta.units as u}<option>{u}</option>{/each}</select>
      chosen by
      <select aria-label="Chosen by" disabled={!d.limit.on} bind:value={d.limit.by}>{#each meta.orders as o}<option>{o}</option>{/each}</select>
    </div>
    <div class="line">
      <label for="smName">Name</label><input id="smName" type="text" bind:value={d.name} />
      <span class="sp"></span><span class="small" class:err={previewErr} class:muted={!previewErr} aria-live="polite">{preview}</span>
    </div>
    {#if err}<p class="err small">{err}</p>{/if}
  {/if}
  {#snippet footer()}
    <button onclick={onclose}>Cancel</button>
    <button class="primary" disabled={!d} onclick={save}>{id ? "Save" : "Create"}</button>
  {/snippet}
</Modal>

<style>
  .line { display: flex; align-items: center; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
  .rules { border: 1px solid var(--line); border-radius: var(--r-md); padding: 6px 8px; max-height: 280px; overflow-y: auto; }
  .rule { display: flex; align-items: center; gap: 6px; padding: 4px 0; }
  .rule input[type="text"] { width: 180px; }
  .rule input[type="number"] { width: 80px; }
  .rule .quiet { padding: 2px 8px; min-height: 26px; }
  .sp { flex: 1; }
  .num { width: 70px; }
  .chk { display: flex; gap: 6px; align-items: center; }
  #smName { width: 240px; }
  .small { font-size: 12px; }
</style>
