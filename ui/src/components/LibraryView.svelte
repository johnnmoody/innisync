<script>
  // The main area for anything that lists songs: library, playlists, the Y1's own songs, similar songs, mixes.
  import SongTable from "./SongTable.svelte";
  import ColumnBrowser from "./ColumnBrowser.svelte";
  import CoverGrid from "./CoverGrid.svelte";
  import Mixes from "./Mixes.svelte";
  import Wheel from "./Wheel.svelte";
  import { st, visibleSongs, keepSimilar, openSimilar, loadLibrary } from "../lib/store.svelte.js";
  import { notice } from "../lib/dialogs.svelte.js";

  let { rows, onSignIn } = $props();
  const browserOn = $derived(st.showBrowser && st.mode !== "grid" && !["playlist", "similar", "devpl"].includes(st.view));
  const seed = $derived(st.byId[st.similar.seed]);
  const emptyText = $derived(st.search ? `No songs match “${st.search}”.`
    : st.view === "playlist" ? "This playlist is empty."
    : st.view === "devmusic" || st.view === "devpl" ? (st.dev ? "No songs here on the Y1." : "Reading the Y1…")
    : st.view === "similar" ? "No similar songs on your Y1 yet. Songs need to be analysed first."
    : "Your library is empty.");
  async function keep() { try { await keepSimilar(); } catch (e) { notice("Couldn't change that", e.message); } }
</script>

<section class="lib">
  {#if st.signedOut}
    <div class="state">
      <Wheel size={56} />
      <h2>Sign in to your music library</h2>
      <p class="muted">InniSync reads your songs and playlists from Jellyfin or a Subsonic server such as Navidrome.</p>
      <button class="primary" onclick={onSignIn}>Sign In…</button>
    </div>
  {:else if st.libLoading && !st.songs.length}
    <div class="state"><Wheel size={40} /><p class="muted">Loading your library…</p></div>
  {:else if st.libError && !st.songs.length}
    <div class="state">
      <h2>Your library didn't load</h2>
      <p class="muted">{st.libError}</p>
      <button onclick={() => loadLibrary(true)}>Try Again</button>
    </div>
  {:else if st.view === "mixes"}
    <Mixes />
  {:else}
    {#if st.view === "similar"}
      <div class="simbar">
        <span>Songs like <b>{seed?.name || "this song"}</b>{seed ? `, ${seed.artist}` : ""}</span>
        <span class="sp"></span>
        <button onclick={() => openSimilar(st.similar.seed)} title="Pick again from the newest analysis">Refresh</button>
        <button onclick={keep} title={st.similar.kept ? "Stop syncing these songs as a playlist" : "Sync these songs to your Y1 as a playlist (rebuilt on every sync)"}>{st.similar.kept ? "Remove from Y1" : "Keep on Y1"}</button>
      </div>
    {/if}
    {#if browserOn}<ColumnBrowser />{/if}
    {#if st.mode === "grid"}
      <CoverGrid {rows} />
    {:else if rows.length}
      <SongTable {rows} />
    {:else}
      <div class="state"><p class="muted">{emptyText}</p></div>
    {/if}
  {/if}
</section>

<style>
  .lib { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--surface); }
  .state { margin: auto; max-width: 420px; padding: 24px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; color: var(--text-2); }
  .state h2 { color: var(--text); font-size: 17px; margin: 6px 0 0; }
  .state p { margin: 0; }
  .simbar { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-bottom: 1px solid var(--line); flex: none; }
  .sp { flex: 1; }
</style>
