<script>
  // The InniSync mark: a click wheel (ring, four control marks, plain centre button).
  let { size = 24, color = "currentColor", fill = false } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
  <circle cx="16" cy="16" r="14.5" fill={fill ? "var(--accent)" : "none"} stroke={color} stroke-width="2" />
  <circle cx="16" cy="16" r="5.5" fill={fill ? "var(--surface)" : "none"} stroke={color} stroke-width="2" />
  <g fill={fill ? "var(--on-accent)" : color}>
    <rect x="13" y="4.6" width="6" height="1.8" rx=".9" />
    <path d="M7.9 14.2v3.6L5.2 16zM10.7 14.2v3.6L8 16z" />
    <path d="M24.1 14.2v3.6l2.7-1.8zM21.3 14.2v3.6L24 16z" />
    <path d="M13.6 24.6v3l2.3-1.5zM17 24.6h1v3h-1zM19 24.6h1v3h-1z" />
  </g>
</svg>
