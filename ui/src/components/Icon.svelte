<script>
  // Small filled glyphs, drawn for InniSync (16 x 16 grid). Each one says what its item holds.
  let { name, size = 16 } = $props();
  const P = {
    // a single note: the music library
    music: "M11 1.5v8.8a2.6 2.6 0 1 1-1.5-2.35V4.2L6 5.1v6.7a2.6 2.6 0 1 1-1.5-2.35V3.4z",
    // a clock face: recently added
    recent: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zm.75 3v3.2l2.4 1.4-.75 1.3-3.15-1.85V4.5z",
    // stacked lines with a note: a playlist
    playlist: "M1.5 3h9v1.5h-9zm0 3.5h9V8h-9zm0 3.5h5.5v1.5H1.5zM13.5 6v5.6a1.9 1.9 0 1 1-1.5-1.86V6z",
    // stacked lines with a sliders mark: a playlist made from rules
    smart: "M1.5 3h7v1.5h-7zm0 3.5h7V8h-7zm0 3.5h7v1.5h-7zM11 2.5h1.5V5H14v1.5h-1.5V14H11V6.5H9.5V5H11z",
    // two overlapping discs: songs mixed by how they sound
    mix: "M6 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zm0 4a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zM10.2 3.05a5.5 5.5 0 0 1 0 9.9 6.9 6.9 0 0 0 0-9.9z",
    // a disc with a connecting arc: songs similar to one song
    similar: "M5 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm0 3a1 1 0 1 1 0 2 1 1 0 0 1 0-2zM11 2.5a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM9.2 9.6l1.2.9-1.8 2.4-1.2-.9z",
    // concentric waves: podcasts
    podcast: "M8 6.2a1.8 1.8 0 1 1 0 3.6 1.8 1.8 0 0 1 0-3.6zM4.1 12.5a5.5 5.5 0 1 1 7.8 0l-1.06-1.06a4 4 0 1 0-5.68 0z",
    // an open book: audiobooks
    book: "M1.5 3c2.4 0 4.6.5 5.75 1.6V14C6.1 13 3.9 12.5 1.5 12.5zm13 0v9.5c-2.4 0-4.6.5-5.75 1.5V4.6C9.9 3.5 12.1 3 14.5 3z",
    // a framed picture: themes
    theme: "M1.5 2.5h13v11h-13zm1.5 1.5v6.6l3-3 2.6 2.6 1.6-1.6L13 11.4V4zm7.75 1a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5z",
    // a gear: settings
    gear: "M6.9 1.5h2.2l.35 1.8 1.1.45 1.5-1.05 1.55 1.55-1.05 1.5.45 1.1 1.8.35v2.2l-1.8.35-.45 1.1 1.05 1.5-1.55 1.55-1.5-1.05-1.1.45-.35 1.8H6.9l-.35-1.8-1.1-.45-1.5 1.05-1.55-1.55 1.05-1.5-.45-1.1-1.8-.35V6.9l1.8-.35.45-1.1-1.05-1.5L3.95 2.4l1.5 1.05 1.1-.45zM8 5.6a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z",
    // a downward arrow into a tray: wanted downloads (Lidarr)
    wanted: "M7.25 1.5h1.5v6.7l2.2-2.2 1.06 1.06L8 11.06 3.99 7.06 5.05 6l2.2 2.2zM1.5 10h1.5v2.5h10V10h1.5v4h-13z",
    play: "M4 2.5v11l9-5.5z",
    pause: "M3.5 2.5h3v11h-3zm6 0h3v11h-3z",
    next: "M2 3v10l5.5-5zm6 0v10l5.5-5zm5.5 0H15v10h-1.5z",
    prev: "M14 3v10L8.5 8zM8 3v10L2.5 8zM1 3h1.5v10H1z",
    shuffle: "M1.5 4h3.2l5 7h2.3V9.5l3 2.25-3 2.25V12.5H8.9l-5-7H1.5zm8.1 0H12V2.5l3 2.25L12 7V5.5H10.4l-1.5 2.1-.9-1.3zM1.5 12.5V11h2.4l1.5-2.1.9 1.3-1.6 2.3z",
    repeat: "M3 5.5A2.5 2.5 0 0 1 5.5 3H11V1.5l3 2.25L11 6V4.5H5.5a1 1 0 0 0-1 1V8H3zm10 5A2.5 2.5 0 0 1 10.5 13H5v1.5L2 12.25 5 10v1.5h5.5a1 1 0 0 0 1-1V8H13z",
    list: "M1.5 3h13v1.5h-13zm0 3.5h13V8h-13zm0 3.5h13v1.5h-13z",
    albums: "M1.5 2.5h5v5h-5zm6.5 1h6.5V5H8zm0 2.5h4.5v1.5H8zM1.5 9h5v5h-5zm6.5 1h6.5v1.5H8zm0 2.5h4.5V14H8z",
    grid: "M1.5 1.5h5.75v5.75H1.5zm7.25 0h5.75v5.75H8.75zM1.5 8.75h5.75v5.75H1.5zm7.25 0h5.75v5.75H8.75z",
    columns: "M1.5 2.5h13v11h-13zM3 4v8h2.5V4zm4 0v8h2V4zm3.5 0v8H13V4z",
    plus: "M7.25 2.5h1.5v4.75h4.75v1.5H8.75v4.75h-1.5V8.75H2.5v-1.5h4.75z",
    close: "M3.4 2.3 8 6.9l4.6-4.6 1.1 1.1L9.1 8l4.6 4.6-1.1 1.1L8 9.1l-4.6 4.6-1.1-1.1L6.9 8 2.3 3.4z",
    chevron: "M6 3.5 10.5 8 6 12.5l-1.06-1.06L8.38 8 4.94 4.56z",
    volume: "M1.5 5.5h3L8.5 2v12l-4-3.5h-3zM10.5 5.2a3.5 3.5 0 0 1 0 5.6l-.9-1.2a2 2 0 0 0 0-3.2zm1.8-2.4a6.5 6.5 0 0 1 0 10.4l-.9-1.2a5 5 0 0 0 0-8z",
    search: "M6.75 1.5a5.25 5.25 0 0 1 4.2 8.4l3.55 3.55-1.06 1.06-3.55-3.55A5.25 5.25 0 1 1 6.75 1.5zm0 1.5a3.75 3.75 0 1 0 0 7.5 3.75 3.75 0 0 0 0-7.5z",
  };
</script>

<svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" fill="currentColor"><path d={P[name]} fill-rule="evenodd" /></svg>
