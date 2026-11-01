<script>
  import { st, refreshDevice } from "../../lib/store.svelte.js";
  import { api, upload, devImg } from "../../lib/api.js";
  import { confirm, notice } from "../../lib/dialogs.svelte.js";

  let themes = $state(null), err = $state(""), status = $state(""), wp = $state(null), zipPicker = $state(), wpPicker = $state();
  let catalog = $state(null), catOpen = $state(false), catErr = $state(""), q = $state(""), installing = $state(null);
  const usb = $derived(st.device.transport !== "wifi");

  async function load() {
    err = "";
    try { themes = await api("/api/device/themes"); } catch (e) { err = e.message; return; }
    loadWallpaper();
  }
  async function loadWallpaper() {
    try {
      const p = await api("/api/device/player");
      const cur = themes?.themes.find((x) => x.name === themes.current);
      wp = { ...p, img: p.wallpaper || (p.themeWallpaper && cur?.bg) || null, themeHasBg: !!cur?.bg };
    } catch (e) { wp = { error: e.message }; }
  }
  $effect(() => { load(); });

  // a theme's colours come as ARGB hex (#AARRGGBB) or #RRGGBB
  const argb = (c, fb) => {
    const m = /^#?([0-9a-f]{8})$/i.exec(c || "");
    if (!m) return /^#[0-9a-f]{6}$/i.test(c || "") ? c : fb;
    const h = m[1];
    return `rgba(${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${parseInt(h.slice(6, 8), 16)},${(parseInt(h.slice(0, 2), 16) / 255).toFixed(2)})`;
  };
  const dup = (name) => themes.themes.filter((x) => x.name === name).length > 1;
  async function act(fn, done = "") {
    try { status = done; await fn(); } catch (e) { notice("That didn't work", e.message); }
    status = ""; load(); refreshDevice(true);
  }
  const use = (t) => act(() => api("/api/device/themes/use", { name: t.name }), `Switching to ${t.name}…`);
  async function removeInni(t) { if (await confirm(`Remove ${t.folder} from the Y1?`, "", "Remove", true)) act(() => api("/api/device/themes/remove", { kind: "inni", folder: t.folder })); }
  async function removeStock(t) { if (await confirm(`Remove ${t.name} from the Y1?`, "", "Remove", true)) act(() => api("/api/device/themes/remove", { kind: "stock", folder: t.folder })); }
  async function addZip(e) {
    const f = e.currentTarget.files[0]; e.currentTarget.value = ""; if (!f) return;
    status = `Copying ${f.name}…`;
    try { const r = await upload("/api/device/themes/upload", f); status = `Added ${r.name}. Click Use to switch to it.`; } catch (er) { status = ""; notice("The theme wasn't added", er.message); }
    load();
  }
  async function addWallpaper(e) {
    const f = e.currentTarget.files[0]; e.currentTarget.value = ""; if (!f) return;
    wp = { ...wp, busy: "Fitting it to the Y1's 480 × 360 screen and copying…" };
    try { await upload("/api/device/wallpaper", f); } catch (er) { notice("The picture wasn't set", er.message); }
    loadWallpaper();
  }
  async function setWallpaper(kind) { await api("/api/device/player", { wallpaper: kind }).catch((e) => notice("That didn't work", e.message)); loadWallpaper(); }
  async function openCatalog() {
    catOpen = !catOpen;
    if (!catOpen || catalog) return;
    try { catalog = await api("/api/themes/catalog"); } catch (e) { catErr = e.message; }
  }
  const have = $derived(new Set((themes?.stock || []).map((x) => x.folder)));
  const found = $derived(catalog ? catalog.themes.filter((t) => !q || `${t.name} ${t.author} ${t.description}`.toLowerCase().includes(q.toLowerCase())) : []);
  const raw = (repo, path) => `https://raw.githubusercontent.com/${repo}/main/` + path.split("/").map(encodeURIComponent).join("/");
  async function install(t) {
    installing = t.folder;
    try { await api("/api/themes/install", { folder: t.folder }); } catch (e) { notice("The theme wasn't copied", e.message); }
    installing = null; load();
  }
</script>

<div class="card">
  <h2>Theme</h2>
  <p class="note">Themes for InniClassic, the player on your Y1. Switching restarts the player, which stops anything playing.</p>
  {#if err}<p class="err">{err}</p><button onclick={load}>Try Again</button>
  {:else if !themes}<p class="muted">Reading the Y1…</p>
  {:else}
    <div class="grid">
      {#each themes.themes as t (t.folder ?? t.name)}
        {@const c = t.colors || {}}
        {@const cur = t.name === themes.current}
        <div class="tcard" class:cur>
          <div class="mock" style:background={t.bg ? `center/cover url(${JSON.stringify(devImg(t.bg))})` : "linear-gradient(#3a3d44,#15161a)"} aria-hidden="true">
            <div class="mbar" style:background={argb(c.statusBarBg, "rgba(0,0,0,.35)")} style:color={argb(c.textPrimary, "#fff")}>{st.device.name}</div>
            <div class="mlist" style:background={argb(c.bgOverlay, "rgba(0,0,0,.55)")}>
              {#each ["Now Playing", "Music", "Videos", "Playlists", "Settings"] as r, i}
                <div style:background={i === 1 ? argb(c.btnFocused, "rgba(255,255,255,.85)") : "none"} style:color={i === 1 ? argb(c.btnFocusedText, "#000") : argb(c.textPrimary, "#fff")}>{r}</div>
              {/each}
            </div>
          </div>
          <div class="tname" title={t.folder ? `Folder ${t.folder}` : "Built into InniClassic"}>{t.name}{#if dup(t.name) && t.folder}<span class="muted"> ({t.folder})</span>{/if}</div>
          <div class="tbtns">
            {#if cur}<span class="inuse">In use</span>
            {:else}<button disabled={dup(t.name)} title={dup(t.name) ? "Two themes share this name, so InniClassic can't tell them apart" : ""} onclick={() => use(t)}>Use</button>{/if}
            {#if t.folder && !cur}<button class="link" onclick={() => removeInni(t)}>Remove</button>{/if}
          </div>
        </div>
      {/each}
    </div>
    <div class="row">
      <button disabled={!usb} onclick={() => zipPicker.click()}>Add Theme…</button>
      <input class="sr" type="file" accept=".zip,application/zip" bind:this={zipPicker} onchange={addZip} tabindex="-1" aria-hidden="true" />
      <span class="muted small">{usb ? status : "Connect the Y1 by USB to add themes."}</span>
    </div>
  {/if}
</div>

<div class="card">
  <h2>Wallpaper</h2>
  <div class="wp">
    <div class="wpprev">{#if wp?.img}<img src={devImg(wp.img)} alt="Current wallpaper" width="160" height="120" />{/if}</div>
    <div>
      <p class="note">{wp?.error || wp?.busy || (!wp ? "Reading the Y1…" : wp.wallpaper ? "Your own picture." : wp.themeWallpaper ? "The theme's own wallpaper." : "No wallpaper.")}</p>
      <div class="row">
        <button disabled={!usb} onclick={() => wpPicker.click()}>Choose Picture…</button>
        <input class="sr" type="file" accept="image/*" bind:this={wpPicker} onchange={addWallpaper} tabindex="-1" aria-hidden="true" />
        <button disabled={!wp?.themeHasBg || wp?.themeWallpaper} onclick={() => setWallpaper("theme")}>Use Theme's Wallpaper</button>
        <button disabled={!wp?.wallpaper && !wp?.themeWallpaper} onclick={() => setWallpaper("none")}>None</button>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <h2>Themes for the original Y1 player</h2>
  <p class="note">These are for the player the Y1 came with, not InniClassic. They're copied to the Y1's Themes folder and only show if you switch back to that player.</p>
  {#if themes}
    <div class="grid">
      {#each themes.stock as t (t.folder)}
        <div class="tcard"><div class="cover">{#if t.cover}<img src={devImg(t.cover)} alt="" loading="lazy" />{/if}</div>
          <div class="tname" title="{t.name}{t.author ? ` by ${t.author}` : ''}">{t.name}</div>
          <div class="tbtns"><button class="link" onclick={() => removeStock(t)}>Remove</button></div></div>
      {:else}<p class="muted">None on the Y1.</p>{/each}
    </div>
  {/if}
  <div class="row"><button aria-expanded={catOpen} onclick={openCatalog}>{catOpen ? "Hide Community Themes" : "Browse Community Themes…"}</button></div>
  {#if catOpen}
    {#if catErr}<p class="err">{catErr}</p>
    {:else if !catalog}<p class="muted">Loading themes from GitHub…</p>
    {:else}
      <div class="row"><label class="sr" for="catq">Search themes</label><input id="catq" type="search" placeholder="Search themes" bind:value={q} /><span class="muted small">{found.length.toLocaleString()} of {catalog.themes.length.toLocaleString()}</span></div>
      <div class="grid">
        {#each found.slice(0, 240) as t (t.folder)}
          <div class="tcard"><div class="cover">{#if t.screenshot}<img src={raw(catalog.repo, t.screenshot)} alt="" loading="lazy" onerror={(e) => e.currentTarget.remove()} />{/if}</div>
            <div class="tname" title="{t.name}{t.description ? `: ${t.description}` : ''}">{t.name}</div><div class="muted small">{t.author}</div>
            <div class="tbtns">{#if have.has(t.folder)}<span class="inuse">On the Y1</span>{:else}<button disabled={!usb || installing === t.folder} onclick={() => install(t)}>{installing === t.folder ? "Copying…" : "Copy to Y1"}</button>{/if}</div></div>
        {/each}
      </div>
      {#if found.length > 240}<p class="muted small">Showing the first 240. Search to narrow it down.</p>{/if}
    {/if}
  {/if}
</div>

<style>
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; margin: 12px 0; }
  .tcard { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .tcard.cur .mock { outline: 2px solid var(--accent); outline-offset: 2px; }
  .mock { aspect-ratio: 4 / 3; border-radius: var(--r-sm); overflow: hidden; position: relative; font-size: 8px; }
  .mbar { height: 12%; padding: 0 5px; display: flex; align-items: center; }
  .mlist { position: absolute; left: 0; top: 12%; bottom: 0; width: 52%; padding: 3px; }
  .mlist div { padding: 2px 4px; border-radius: 2px; }
  .cover { aspect-ratio: 4 / 3; border-radius: var(--r-sm); background: var(--line); overflow: hidden; }
  .cover img { width: 100%; height: 100%; object-fit: cover; }
  .tname { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tbtns { display: flex; align-items: center; gap: 10px; }
  .tbtns button:not(.link) { min-height: 24px; padding: 2px 10px; font-size: 12px; }
  .inuse { font-size: 12px; color: var(--text-2); }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
  .wp { display: flex; gap: 18px; align-items: flex-start; }
  .wpprev { width: 160px; height: 120px; border-radius: var(--r-sm); background: var(--line); overflow: hidden; flex: none; }
  .wpprev img { width: 100%; height: 100%; object-fit: cover; }
  .small { font-size: 12px; }
</style>
