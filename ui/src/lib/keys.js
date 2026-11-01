// Shortcuts use Cmd on a Mac and Ctrl elsewhere; hints in tooltips say which.
export const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
export const MOD = MAC ? "Cmd" : "Ctrl";
export const mod = (e) => (MAC ? e.metaKey : e.ctrlKey);
