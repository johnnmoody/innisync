<script>
  import Modal from "../Modal.svelte";
  import { api } from "../../lib/api.js";
  import { fmtWhen } from "../../lib/format.js";
  import { notice } from "../../lib/dialogs.svelte.js";
  let { backups, onclose, ondone } = $props();
  let idx = $state(0), settings = $state(true), playlists = $state(true), busy = $state(false);
  const b = $derived(backups[idx]);
  $effect(() => { if (b && !b.hasPlaylists) playlists = false; });
  async function go() {
    busy = true;
    try {
      const r = await api("/api/device/restore", { path: b.path, settings, playlists });
      ondone(`Restored from ${fmtWhen(b.created)}. The Y1 as it was just before is saved as backup ${r.safety}.`);
    } catch (e) { busy = false; notice("The restore didn't finish", e.message); }
  }
</script>

<Modal title="Restore from a Backup" {onclose} width={480}>
  <label class="pick" for="bk">Backup</label>
  <select id="bk" bind:value={idx}>
    {#each backups as x, i}<option value={i}>{x.device.name || "Y1"}, {fmtWhen(x.created)}{x.reason !== "manual" ? " (automatic)" : ""}</option>{/each}
  </select>
  {#if b}
    <dl>
      <dt>Made</dt><dd>{fmtWhen(b.created)}{b.reason && b.reason !== "manual" ? ` (${b.reason})` : ""}</dd>
      <dt>Saved on</dt><dd>{b.where}</dd>
      <dt>Holds</dt><dd>{b.prefs.length} settings files, {b.hasPlaylists ? `${b.playlists} playlists` : "no playlists"}, InniClassic {b.device.launcher || "?"}</dd>
    </dl>
    <label class="chk"><input type="checkbox" bind:checked={settings} /> Player settings</label>
    <label class="chk"><input type="checkbox" bind:checked={playlists} disabled={!b.hasPlaylists} /> Playlists</label>
    <p class="muted small">The Y1 is backed up as it is now before anything is replaced. The player app restarts.</p>
  {/if}
  {#snippet footer()}
    <button onclick={onclose}>Cancel</button>
    <button class="primary" disabled={busy || (!settings && !playlists)} onclick={go}>{busy ? "Restoring…" : "Restore"}</button>
  {/snippet}
</Modal>

<style>
  .pick { display: block; color: var(--text-2); font-size: 13px; margin-bottom: 4px; }
  select { width: 100%; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 12px 0; font-size: 13px; }
  dt { color: var(--text-2); }
  dd { margin: 0; }
  .chk { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
  .small { font-size: 12px; }
</style>
