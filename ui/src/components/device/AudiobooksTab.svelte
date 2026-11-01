<script>
  import { st, refreshDevice } from "../../lib/store.svelte.js";
  import { api, upload } from "../../lib/api.js";
  import { fmtSize, plural } from "../../lib/format.js";
  import { askText, confirm, notice } from "../../lib/dialogs.svelte.js";
  let books = $state(null), err = $state(""), status = $state(""), picker = $state();
  async function load() {
    err = "";
    try { books = (await api("/api/device/audiobooks")).books; } catch (e) { err = e.message; }
  }
  $effect(() => { load(); });
  async function remove(b) {
    if (!(await confirm(`Remove ${b.book} from the Y1?`, "", "Remove", true))) return;
    try { await api("/api/device/audiobooks/remove", { book: b.book }); } catch (e) { notice("It wasn't removed", e.message); }
    load(); refreshDevice(true);
  }
  async function add(e) {
    const files = [...e.currentTarget.files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    e.currentTarget.value = "";
    if (!files.length) return;
    const stem = files[0].name.replace(/\.[^.]+$/, "");
    const guess = files.length === 1 ? stem : stem.replace(/[\s._-]*(part|chapter|ch|track|disc|cd)?[\s._-]*\d+$/i, "").trim();
    const book = await askText("Book title", "It becomes the folder name on the Y1.", guess, "Add");
    if (!book) return;
    const errs = [];
    for (const [i, f] of files.entries()) {
      status = `Copying ${i + 1} of ${files.length}: ${f.name}`;
      try { await upload(`/api/device/audiobooks/add?book=${encodeURIComponent(book)}&name=${encodeURIComponent(f.name)}`, f); } catch (er) { errs.push(er.message); }
    }
    status = "";
    if (errs.length) notice(`${errs.length} of ${files.length} files weren't added`, errs.join("\n"));
    load(); refreshDevice(true);
  }
</script>

<div class="card">
  <h2>Audiobooks on the Y1</h2>
  <p class="note">Books go in the Y1's Audiobooks folder, the only place it remembers where you stopped and keeps bookmarks. Each book is a folder, played in file-name order. Audible .aax files are copy protected and won't play; .m4b books are repackaged as .m4a so the Y1 lists them.</p>
  <div class="books">
    {#if err}<p class="err">{err}</p><button onclick={load}>Try Again</button>
    {:else if !books}<p class="muted">Reading the Y1…</p>
    {:else}
      {#each books as b (b.book)}
        <div class="book"><b class="t" title={b.book}>{b.book}</b><span class="muted">{plural(b.files.length, "file")}, {fmtSize(b.files.reduce((t, f) => t + f.size, 0))}</span><button class="link" onclick={() => remove(b)}>Remove</button></div>
      {:else}<p class="muted">No audiobooks on the Y1 yet.</p>{/each}
    {/if}
  </div>
  <div class="row">
    <button disabled={st.device.transport === "wifi"} onclick={() => picker.click()}>Add Audiobook…</button>
    <input class="sr" type="file" multiple accept="audio/*,.m4b,.ape,.opus,.wma" bind:this={picker} onchange={add} tabindex="-1" aria-hidden="true" />
    <span class="muted small">{st.device.transport === "wifi" ? "Connect the Y1 by USB to add books." : status}</span>
  </div>
</div>

<style>
  .books { margin: 12px 0; border-top: 1px solid var(--line); }
  .book { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .t { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .row { display: flex; align-items: center; gap: 10px; }
  .small { font-size: 12px; }
  p { margin: 8px 0; }
</style>
