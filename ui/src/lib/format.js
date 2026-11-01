export const fmtTime = (s) => {
  s = Math.max(0, Math.round(s || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
export const fmtSize = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${Math.round((b || 0) / 1e6)} MB`);
export const fmtSpan = (s) =>
  s >= 86400 ? `${(s / 86400).toFixed(1)} days` : s >= 3600 ? `${(s / 3600).toFixed(1)} hours` : `${(s / 60).toFixed(1)} minutes`;
export const fmtWhen = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
export const plural = (n, one, many = one + "s") => `${n.toLocaleString()} ${n === 1 ? one : many}`;
