<script>
  // Podcasts: the Y1's own subscriptions (InniClassic's Podcasts menu); InniSync copies the chosen episodes.
  import Icon from "../Icon.svelte";
  import { st } from "../../lib/store.svelte.js";
  import { api } from "../../lib/api.js";
  import { fmtSize } from "../../lib/format.js";
  import { confirm } from "../../lib/dialogs.svelte.js";

  const s = $derived(st.settings.podcasts);
  let pods = $state(null), cur = $state(null), err = $state(""), url = $state(""), msg = $state("");
  async function load(refresh) {
    err = "";
    try { pods = await api("/api/device/podcasts" + (refresh ? "?refresh=1" : "")); }
    catch (e) { err = e.message; return; }
    if (!pods.podcasts.find((p) => p.url === cur)) cur = pods.podcasts[0]?.url || null;
  }
  $effect(() => { load(); });
  const n = (rule) => (rule === "all" ? Infinity : parseInt(rule, 10));
  const autoSet = (p) => new Set(s.auto && (s.which === "all" || s.selected.includes(p.url)) ? p.episodes.slice(0, n(s.rule)).map((e) => e.url) : []);
  // what the settings put on the Y1 for one podcast (the server's podcasts.wanted does the same)
  const picks = (p) => (!s.sync ? new Set() : new Set([...autoSet(p), ...p.episodes.filter((e) => s.extra.includes(e.url)).map((e) => e.url)]));
  const current = $derived(pods?.podcasts.find((p) => p.url === cur));
  const total = $derived(pods ? pods.podcasts.reduce((t, p) => t + picks(p).size, 0) : 0);
  const day = (e) => (e.date ? new Date(e.date * 1000).toLocaleDateString([], { month: "short", day: "numeric", year: "2-digit" }) : "");
  function setIn(key, v, on) { const a = s[key].filter((x) => x !== v); if (on) a.push(v); s[key] = a; }
  async function subscribe(e) {
    e.preventDefault();
    if (!url.trim()) return;
    msg = "Reading the feed…";
    try { const r = await api("/api/device/podcasts/subscribe", { url: url.trim() }); url = ""; cur = r.url; msg = `Subscribed to ${r.name}.`; await load(true); }
    catch (er) { msg = er.message; }
  }
  async function unsubscribe() {
    const p = current; if (!p) return;
    if (!(await confirm(`Unsubscribe from ${p.name}?`, "The Y1 stops listing it.", "Unsubscribe"))) return;
    const removeEpisodes = await confirm(`Delete the downloaded episodes of ${p.name}?`, "", "Delete", true, "Keep Them");
    try { await api("/api/device/podcasts/unsubscribe", { url: p.url, removeEpisodes }); msg = `Unsubscribed from ${p.name}.`; await load(true); }
    catch (er) { msg = er.message; }
  }
</script>

<div class="wide head">
  <label class="big"><input type="checkbox" bind:checked={s.sync} /> Sync podcasts</label>
  {#if s.sync}<span class="muted">{total} episode{total === 1 ? "" : "s"}</span>{/if}
</div>
<div class="card">
  <div class="rule">
    <label><input type="checkbox" bind:checked={s.auto} disabled={!s.sync} /> Automatically include</label>
    <select aria-label="Which episodes" bind:value={s.rule} disabled={!s.sync || !s.auto}>{#each pods?.rules || [s.rule] as r}<option>{r}</option>{/each}</select>
    <span>episodes of</span>
    <select aria-label="Which podcasts" bind:value={s.which} disabled={!s.sync || !s.auto}><option value="all">every podcast</option><option value="selected">chosen podcasts</option></select>
  </div>
</div>

{#if err}
  <div class="card"><p class="err">{err}</p><button onclick={() => load(true)}>Try Again</button></div>
{:else if !pods}
  <div class="card"><p class="muted">Reading the Y1 and the podcast feeds…</p></div>
{:else}
  <div class="wide lists" class:off={!s.sync}>
    <section>
      <h3>Podcasts</h3>
      <div class="list">
        {#each pods.podcasts as p (p.url)}
          <div class="pod" class:cur={p.url === cur}>
            {#if s.which === "selected"}<input type="checkbox" aria-label="Include {p.name}" checked={s.selected.includes(p.url)} onchange={(e) => setIn("selected", p.url, e.currentTarget.checked)} />{/if}
            <button title={p.error || p.url} onclick={() => (cur = p.url)}><Icon name="podcast" size={14} /><span class="t">{p.name}</span>
              <span class="n">{p.error ? "can't read feed" : picks(p).size ? `${picks(p).size} to sync` : ""}</span></button>
          </div>
        {:else}<p class="muted">No subscriptions on the Y1 yet. Add one below.</p>{/each}
      </div>
    </section>
    <section>
      <h3>Episodes</h3>
      <div class="list">
        {#if current?.error}<p class="err">{current.error}</p>
        {:else if current}
          {@const auto = autoSet(current)}
          {@const chosen = picks(current)}
          {#each current.episodes as e (e.url)}
            <label title="{e.title}{e.size ? `, ${fmtSize(e.size)}` : ''}"><input type="checkbox" checked={chosen.has(e.url)} disabled={auto.has(e.url)} onchange={(ev) => setIn("extra", e.url, ev.currentTarget.checked)} />
              <span class="t">{e.title}</span><span class="n">{e.onY1 ? (e.byInniSync ? "on Y1" : "on Y1, downloaded there") : day(e)}</span></label>
          {/each}
        {/if}
      </div>
    </section>
  </div>
{/if}

<div class="card">
  <form class="sub" onsubmit={subscribe}>
    <label class="sr" for="podUrl">Podcast feed address</label>
    <input id="podUrl" type="url" placeholder="Podcast RSS feed address" bind:value={url} />
    <button type="submit" disabled={!url.trim()}>Subscribe</button>
    <button type="button" disabled={!current} onclick={unsubscribe}>Unsubscribe</button>
  </form>
  {#if msg}<p class="note">{msg}</p>{/if}
  <p class="note">Subscriptions belong to the Y1: they show in its Podcasts menu and it can download episodes itself over Wi-Fi. InniSync copies the episodes chosen here when you sync.</p>
</div>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; }
  .big { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px; }
  .rule { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .rule label { display: flex; align-items: center; gap: 8px; }
  .lists { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 14px; }
  .lists.off { opacity: 0.5; pointer-events: none; }
  h3 { font-size: 12px; color: var(--text-2); margin: 0 0 6px; font-weight: 600; }
  .list { height: 300px; overflow-y: auto; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 4px 0; }
  .list p { margin: 0; padding: 6px 10px; font-size: 13px; }
  .pod { display: flex; align-items: center; gap: 6px; padding-left: 10px; }
  .pod.cur { background: var(--accent-soft); }
  .pod button { flex: 1; display: flex; align-items: center; gap: 7px; border: 0; background: none; padding: 4px 10px 4px 0; text-align: left; min-width: 0; font-size: 13px; }
  .pod:not(.cur):hover { background: var(--hover); }
  .pod :global(svg) { color: var(--text-2); flex: none; }
  .list label { display: flex; align-items: center; gap: 7px; padding: 3px 10px; font-size: 13px; }
  .t { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .n { color: var(--text-2); font-size: 11px; white-space: nowrap; }
  .sub { display: flex; gap: 8px; }
  .sub input { flex: 1; }
</style>
