<script>
  // InniClassic's own settings, saved to the Y1 with Apply (the player restarts to pick them up).
  import { st } from "../../lib/store.svelte.js";
  import { api } from "../../lib/api.js";
  let err = $state("");
  const EQ = ["Normal", "Classical", "Dance", "Flat", "Folk", "Heavy Metal", "Hip Hop", "Jazz", "Pop", "Rock"];
  const LIGHT = ["10 seconds", "20 seconds", "30 seconds", "1 minute", "2 minutes", "Always on"];
  const autoplayBuild = $derived(st.device.launcher_pkg === "com.themoon.y1.autoplay");
  async function load() {
    if (st.player && JSON.stringify(st.player) !== JSON.stringify(st.playerSaved)) return;   // keep unsaved changes
    err = "";
    try { const p = await api("/api/device/player"); st.player = p.settings; st.playerSaved = structuredClone(p.settings); } catch (e) { err = e.message; }
  }
  $effect(() => { load(); });
  const p = $derived(st.player);
</script>

{#if err}
  <div class="card"><p class="err">{err}</p><button onclick={load}>Try Again</button></div>
{:else if !p}
  <div class="card"><p class="muted">Reading the Y1's settings…</p></div>
{:else}
  <div class="card">
    <h2>Playback</h2>
    <div class="g">
      <span class="k">Shuffle</span><label><input type="checkbox" bind:checked={p.shuffle} /> Shuffle songs</label>
      <label class="k" for="rep">Repeat</label><select id="rep" bind:value={p.repeat_mode}><option value={0}>Off</option><option value={1}>One song</option><option value={2}>All</option></select>
      <label class="k" for="eq">Equalizer</label><select id="eq" bind:value={p.eq_preset}>{#each EQ as n, i}<option value={i}>{n}</option>{/each}</select>
      <span class="k">Sound Check</span><label><input type="checkbox" bind:checked={p.sound_check_enabled} /> Play songs at the same volume</label>
      {#if autoplayBuild}<span class="k">Autoplay</span><label><input type="checkbox" bind:checked={p.autoplay} /> When the queue ends, keep playing songs that go with the last one</label>{/if}
    </div>
  </div>
  <div class="card">
    <h2>Screen and buttons</h2>
    <div class="g">
      <label class="k" for="bl">Backlight</label><select id="bl" bind:value={p.backlight_timer_index}>{#each LIGHT as n, i}<option value={i}>{n}</option>{/each}</select>
      <span class="k">Clicker</span><label><input type="checkbox" bind:checked={p.sound} /> Click sound on the wheel</label>
      <span class="k">Vibration</span><label><input type="checkbox" bind:checked={p.vibrate} /> Vibrate on button presses</label>
      <span class="k">Clock</span><label><input type="checkbox" bind:checked={p.is_24h_format} /> 24-hour time</label>
      <span></span><label><input type="checkbox" bind:checked={p.time_in_title_bar} /> Show the time in the title bar</label>
    </div>
  </div>
  <p class="wide note">Changes are saved to the Y1 when you click Apply. The player restarts to pick them up, which stops anything playing.</p>
{/if}

<style>
  .g { display: grid; grid-template-columns: 130px 1fr; gap: 10px 14px; align-items: center; }
  .k { color: var(--text-2); text-align: right; }
  .g label:not(.k) { display: flex; align-items: center; gap: 8px; }
  select { justify-self: start; min-width: 180px; }
</style>
