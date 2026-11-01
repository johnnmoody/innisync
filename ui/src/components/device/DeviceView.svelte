<script>
  import Summary from "./Summary.svelte";
  import MusicTab from "./MusicTab.svelte";
  import PodcastsTab from "./PodcastsTab.svelte";
  import AudiobooksTab from "./AudiobooksTab.svelte";
  import ThemesTab from "./ThemesTab.svelte";
  import SettingsTab from "./SettingsTab.svelte";
  import CapacityBar from "./CapacityBar.svelte";
  import { st, updatePlan } from "../../lib/store.svelte.js";
  const TABS = [["summary", "Summary"], ["music", "Music"], ["podcasts", "Podcasts"], ["books", "Audiobooks"], ["themes", "Themes"], ["settings", "Settings"]];
  // any change to what syncs re-plans (capacity preview)
  $effect(() => { JSON.stringify(st.settings); if (st.settings) updatePlan(); });
</script>

<section class="dev">
  <div class="tabs" role="tablist" aria-label="{st.device.name} pages">
    {#each TABS as [k, label]}
      <button role="tab" id="tab-{k}" aria-selected={st.tab === k} aria-controls="pane" class:on={st.tab === k} onclick={() => (st.tab = k)}>{label}</button>
    {/each}
  </div>
  <div class="pane" id="pane" role="tabpanel" aria-labelledby="tab-{st.tab}">
    {#if st.tab === "summary"}<Summary />
    {:else if st.tab === "music"}<MusicTab />
    {:else if st.tab === "podcasts"}<PodcastsTab />
    {:else if st.tab === "books"}<AudiobooksTab />
    {:else if st.tab === "themes"}<ThemesTab />
    {:else}<SettingsTab />{/if}
  </div>
  <CapacityBar />
</section>

<style>
  .dev { display: flex; flex-direction: column; min-height: 0; background: var(--bg); }
  .tabs { display: flex; gap: 2px; padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--surface); flex: none; }
  .tabs button { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none; padding: 10px 12px 8px; color: var(--text-2); }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
  .pane { flex: 1; overflow-y: auto; padding: 20px 24px 28px; }
  .pane :global(.card) { max-width: 820px; margin: 0 auto 16px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 14px 18px; }
  .pane :global(.card h2) { font-size: 14px; margin: 0 0 10px; }
  .pane :global(.note) { font-size: 12px; color: var(--text-2); margin: 6px 0 0; }
  .pane :global(.wide) { max-width: 820px; margin: 0 auto 16px; }
</style>
