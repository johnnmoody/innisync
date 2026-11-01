<script>
  // A dialog window over a dimmed app: Escape or the close button closes it, Tab stays inside it,
  // and focus goes back to where it was when it closes.
  import Icon from "./Icon.svelte";
  let { title, onclose, width = 460, children, footer } = $props();
  let box = $state();
  const back = typeof document !== "undefined" ? document.activeElement : null;

  $effect(() => {
    const first = box?.querySelector("input, select, textarea, button:not(.x)");
    (first || box)?.focus();
    return () => back?.focus?.();
  });

  function keys(e) {
    if (e.key === "Escape") { e.stopPropagation(); onclose(); return; }
    if (e.key !== "Tab") return;
    const f = [...box.querySelectorAll("button, input, select, textarea, a[href], [tabindex]:not([tabindex='-1'])")].filter((el) => !el.disabled && el.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
    else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
  }
</script>

<div class="scrim" role="presentation" onmousedown={(e) => e.target === e.currentTarget && onclose()}>
  <div class="win" role="dialog" aria-modal="true" aria-label={title} tabindex="-1" bind:this={box} onkeydown={keys} style:width="{width}px">
    <header><h2>{title}</h2><button class="quiet x" aria-label="Close" onclick={onclose}><Icon name="close" size={14} /></button></header>
    <div class="body">{@render children()}</div>
    {#if footer}<footer>{@render footer()}</footer>{/if}
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; background: var(--scrim); display: grid; place-items: start center; padding: 72px 16px 16px; z-index: 50; }
  /* the one place with elevation: a dialog sits above the app */
  .win { max-width: 100%; max-height: calc(100vh - 96px); display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--r-md); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.22); outline: none; }
  header { display: flex; align-items: center; justify-content: space-between; padding: 12px 12px 4px 18px; }
  h2 { font-size: 15px; font-weight: 700; margin: 0; }
  .x { min-height: 26px; padding: 4px 6px; color: var(--text-2); }
  .body { padding: 8px 18px 14px; overflow: auto; }
  footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--line); }
</style>
