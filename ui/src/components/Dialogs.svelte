<script>
  import Modal from "./Modal.svelte";
  import { dlg, answer } from "../lib/dialogs.svelte.js";
  let text = $state("");
  $effect(() => { if (dlg.current?.kind === "text") text = dlg.current.value ?? ""; });
  const cancel = () => answer(dlg.current?.kind === "text" ? null : false);
  const ok = () => answer(dlg.current.kind === "text" ? text.trim() || null : true);
</script>

{#if dlg.current}
  {@const d = dlg.current}
  <Modal title={d.title} onclose={cancel} width={420}>
    {#if d.message}<p class="msg">{d.message}</p>{/if}
    {#if d.kind === "text"}
      <form onsubmit={(e) => { e.preventDefault(); ok(); }}>
        <label class="sr" for="dlgText">{d.title}</label>
        <input id="dlgText" type="text" bind:value={text} />
      </form>
    {/if}
    {#snippet footer()}
      {#if d.kind !== "notice"}<button onclick={cancel}>{d.cancel || "Cancel"}</button>{/if}
      <button class="primary" class:danger={d.danger} onclick={ok}>{d.ok}</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .msg { margin: 0 0 10px; color: var(--text-2); white-space: pre-line; max-height: 50vh; overflow-y: auto; }
  input { width: 100%; }
  .danger { background: var(--danger); border-color: var(--danger); color: var(--surface); }
</style>
