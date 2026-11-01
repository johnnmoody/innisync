<script>
  import Modal from "./Modal.svelte";
  import { st, savePrefs, loadLibrary } from "../lib/store.svelte.js";
  import { api } from "../lib/api.js";
  import { MAC } from "../lib/keys.js";
  import { Y1_COLORS, y1Svg } from "../lib/y1.js";
  import { accentFor } from "../lib/accent.js";

  let { pane = "general", startSignIn = false, onclose } = $props();
  // svelte-ignore state_referenced_locally
  let tab = $state(pane);   // the page Preferences opens on; the tabs change it from there
  let auth = $state(null), backend = $state("jellyfin");
  let jfServer = $state(""), ssServer = $state(""), ssUser = $state(""), ssPass = $state(""), ssMsg = $state("");
  let qc = $state(null), qcTimer;   // {code, wait}
  let p = $state(structuredClone($state.snapshot(st.prefs) || {}));
  let saving = $state(false);
  const dark = typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches;

  async function loadAuth() {
    auth = await api("/api/auth");
    backend = auth.backend;
    jfServer = auth.jellyfinServer || ""; ssServer = auth.subsonicServer || ""; ssUser = auth.subsonicUser || "";
  }
  $effect(() => {
    loadAuth().then(() => { if (startSignIn && !auth.signedIn && backend === "jellyfin" && jfServer) quickConnect(); });
    api("/api/prefs").then((r) => (p = r));
    return () => clearTimeout(qcTimer);
  });

  const active = $derived(auth && auth.signedIn && auth.backend === backend);
  async function quickConnect() {
    qc = { code: "······", wait: "Contacting the server…" };
    try {
      const r = await api("/api/auth/quickconnect/start", { server: jfServer.trim() });
      jfServer = r.server;
      qc = { code: r.code, wait: `Waiting for approval on ${r.serverName}…` };
      const poll = async () => {
        const s = await api("/api/auth/quickconnect/poll").catch((e) => ({ state: "error", error: e.message }));
        if (s.state === "signed_in") { qc = null; await loadAuth(); loadLibrary(true); return; }
        if (s.state === "error") { qc = { ...qc, wait: s.error }; return; }
        qcTimer = setTimeout(poll, 2000);
      };
      poll();
    } catch (e) { qc = { code: "", wait: e.message }; }
  }
  async function copyCode() { try { await navigator.clipboard.writeText(qc.code); qc = { ...qc, copied: true }; } catch { /* the code is selectable */ } }
  async function subsonicSignIn(e) {
    e.preventDefault();
    ssMsg = "Signing in…";
    try {
      const r = await api("/api/auth/subsonic", { server: ssServer.trim(), user: ssUser.trim(), password: ssPass });
      ssPass = ""; ssMsg = `Connected to ${r.type} ${r.version || ""}`.trim();
      await loadAuth(); loadLibrary(true);
    } catch (err) { ssMsg = err.message; }
  }
  async function signOut() { await api("/api/auth/signout", {}); await loadAuth(); loadLibrary(); }
  async function ok() {
    saving = true;
    try { await savePrefs({ ...p, lrclib_url: (p.lrclib_url || "").trim() || "https://lrclib.net", lidarr_url: (p.lidarr_url || "").trim(), backup_folder: (p.backup_folder || "").trim() }); onclose(); }
    finally { saving = false; }
  }
</script>

<Modal title="Preferences" {onclose} width={600}>
  <div class="tabs" role="tablist" aria-label="Preference sections">
    {#each [["general", "General"], ["devices", "Devices"], ["advanced", "Advanced"]] as [k, label]}
      <button role="tab" aria-selected={tab === k} class:on={tab === k} onclick={() => (tab = k)}>{label}</button>
    {/each}
  </div>

  {#if tab === "general"}
    <div class="grid">
      <span class="k">Music server</span>
      <div class="radios" role="radiogroup" aria-label="Music server">
        <label><input type="radio" bind:group={backend} value="jellyfin" /> Jellyfin</label>
        <label><input type="radio" bind:group={backend} value="subsonic" /> Navidrome or another Subsonic server</label>
      </div>
      <span class="k">Account</span>
      <div>{#if !auth}<span class="muted">Checking…</span>{:else if auth.signedIn}Signed in as <b>{auth.user}</b>{auth.server ? ` on ${auth.server.replace(/^https?:\/\//, "")}` : ""} ({auth.backend === "subsonic" ? "Subsonic" : "Jellyfin"}){:else}<span class="muted">Not signed in</span>{/if}</div>

      {#if active}
        <span></span><div><button onclick={signOut}>Sign Out</button></div>
      {:else if backend === "jellyfin"}
        <label class="k" for="jfServer">Server address</label>
        <input id="jfServer" type="url" placeholder="http://192.168.1.10:8096" bind:value={jfServer} />
        <span></span><div><button class="primary" disabled={!jfServer.trim()} onclick={quickConnect}>Sign In with Quick Connect…</button></div>
      {:else}
        <label class="k" for="ssServer">Server address</label>
        <input id="ssServer" type="url" placeholder="https://music.example.com" bind:value={ssServer} />
        <label class="k" for="ssUser">User name</label>
        <input id="ssUser" type="text" autocomplete="username" bind:value={ssUser} />
        <label class="k" for="ssPass">Password</label>
        <form onsubmit={subsonicSignIn}><input id="ssPass" type="password" autocomplete="current-password" bind:value={ssPass} /></form>
        <span></span><div class="row"><button class="primary" disabled={!ssServer.trim() || !ssUser.trim() || !ssPass} onclick={subsonicSignIn}>Sign In</button><span class="muted small">{ssMsg}</span></div>
      {/if}
    </div>
    {#if qc && !active}
      <div class="qc">
        <div class="row"><output class="code" aria-label="Quick Connect code">{qc.code}</output>{#if qc.code && qc.code !== "······"}<button onclick={copyCode}>{qc.copied ? "Copied" : "Copy"}</button>{/if}</div>
        <p class="muted">On a device already signed in to Jellyfin (the web page or an app), open Settings, then Quick Connect, and enter this code. InniSync signs in as soon as you approve it.</p>
        <p class="small">{qc.wait}</p>
      </div>
    {/if}
    <p class="note muted">{backend === "jellyfin" ? "InniSync signs in as your own Jellyfin user. You can revoke it any time in Jellyfin's list of devices." : "Your password stays in this computer's keychain. Only a salted token is sent to the server."}</p>

  {:else if tab === "devices"}
    <div class="sub">Your Y1's colour</div>
    <div class="swatches" role="radiogroup" aria-label="Y1 colour">
      {#each Object.entries(Y1_COLORS) as [k, [label]]}
        <button class="sw" class:on={p.y1_color === k} role="radio" aria-checked={p.y1_color === k} title={label} onclick={() => (p.y1_color = k)}>
          <span class="dev" aria-hidden="true">{@html y1Svg(k)}</span><span class="small">{label}</span></button>
      {/each}
    </div>
    <div class="sub">Accent colour</div>
    <div class="radios col" role="radiogroup" aria-label="Accent colour">
      <label><input type="radio" bind:group={p.accent} value="y1" /> <span class="chip" style:background={accentFor(p.y1_color || "black", dark).accent}></span> Match my Y1</label>
      <label><input type="radio" bind:group={p.accent} value="grey" /> <span class="chip" style:background={accentFor("grey", dark).accent}></span> Grey</label>
    </div>
    <div class="sub">When the Y1 connects</div>
    <div class="checks">
      <label><input type="checkbox" bind:checked={p.auto_sync} /> Sync automatically with its saved Music settings</label>
      <label><input type="checkbox" bind:checked={p.auto_backup} /> Back it up automatically (at most once an hour)</label>
      {#if MAC}<label><input type="checkbox" bind:checked={p.show_menubar} /> Show InniSync in the menu bar (after the next launch)</label>{/if}
    </div>
    <div class="grid">
      <label class="k" for="bkFolder">Backup folder</label>
      <input id="bkFolder" type="text" placeholder="Leave empty to keep backups on this computer" bind:value={p.backup_folder} />
    </div>
    <p class="note muted">A folder on a network drive or external disk works. When it isn't there, backups go to this computer instead.</p>

  {:else}
    <div class="grid">
      <label class="k" for="lidarr">Lidarr address</label>
      <input id="lidarr" type="url" placeholder="Optional, e.g. http://192.168.1.10:8686" bind:value={p.lidarr_url} />
      <label class="k" for="lrclib">LRCLIB address</label>
      <input id="lrclib" type="url" placeholder="https://lrclib.net" bind:value={p.lrclib_url} />
      <span class="k">Log file</span><code class="small">{p.log}</code>
    </div>
    <p class="note muted">With a Lidarr address, a Wanted item in the sidebar opens its missing albums. LRCLIB supplies timed lyrics; you can run your own copy.</p>
  {/if}

  {#snippet footer()}
    <button onclick={onclose}>Cancel</button>
    <button class="primary" disabled={saving} onclick={ok}>OK</button>
  {/snippet}
</Modal>

<style>
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin: 0 -18px 14px; padding: 0 18px; }
  .tabs button { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none; padding: 6px 10px; color: var(--text-2); }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); }
  .grid { display: grid; grid-template-columns: 130px 1fr; gap: 10px 12px; align-items: center; margin-bottom: 10px; }
  .k { color: var(--text-2); text-align: right; }
  .grid input, .grid form input { width: 100%; }
  .radios { display: flex; gap: 14px; flex-wrap: wrap; }
  .radios.col { flex-direction: column; gap: 6px; margin-bottom: 6px; }
  .radios label, .checks label { display: flex; align-items: center; gap: 8px; }
  .checks { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
  .row { display: flex; align-items: center; gap: 10px; }
  .sub { font-weight: 700; font-size: 13px; margin: 12px 0 8px; }
  .sub:first-child { margin-top: 0; }
  .swatches { display: grid; grid-template-columns: repeat(9, 1fr); gap: 4px; }
  .sw { display: flex; flex-direction: column; align-items: center; gap: 4px; border: 1px solid transparent; background: none; padding: 6px 2px; }
  .sw.on { border-color: var(--accent); background: var(--accent-soft); }
  .dev { width: 22px; height: 35px; display: flex; }
  .dev :global(svg) { width: 100%; height: 100%; }
  .chip { width: 14px; height: 14px; border-radius: 50%; display: inline-block; }
  .qc { border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px; margin: 4px 0 10px; }
  .code { font-size: 26px; font-weight: 700; letter-spacing: 0.12em; user-select: text; -webkit-user-select: text; font-variant-numeric: tabular-nums; }
  .qc p { margin: 8px 0 0; }
  .note { font-size: 12px; margin: 8px 0 0; }
  .small { font-size: 12px; }
  code { user-select: text; -webkit-user-select: text; overflow-wrap: anywhere; }
</style>
