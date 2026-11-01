// The accent is the user's Y1 colour (or plain grey). Several Y1 colours are pale, so the accent is
// darkened (light theme) or lightened (dark theme) until it stands out from the background by 3:1, the
// WCAG minimum for UI parts, and text on it is whichever of black/white reads at 4.5:1 or better.
import { Y1_COLORS } from "./y1.js";

export const GREY = "#7c7c82";

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const hex = (c) => "#" + c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
const lum = (c) => {
  const [r, g, b] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a, b) => { const [x, y] = [lum(rgb(a)), lum(rgb(b))].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const mix = (a, b, t) => hex(rgb(a).map((v, i) => v + (rgb(b)[i] - v) * t));

export function accentFor(key, dark) {
  const base = key === "grey" ? GREY : (Y1_COLORS[key] || Y1_COLORS.black)[1];
  const bg = dark ? "#1d1d20" : "#ffffff";
  const toward = dark ? "#ffffff" : "#000000";
  let fill = base;
  for (let t = 0.04; contrast(fill, bg) < 3 && t <= 1; t += 0.04) fill = mix(base, toward, t);
  const on = contrast(fill, "#000000") >= contrast(fill, "#ffffff") ? "#000000" : "#ffffff";
  // if neither black nor white reaches 4.5:1 on it, push the fill further until one does
  for (let t = 0.04; contrast(fill, on) < 4.5 && t <= 1; t += 0.04) fill = mix(fill, on === "#000000" ? "#ffffff" : "#000000", t);
  return { accent: fill, onAccent: on, soft: `color-mix(in srgb, ${fill} ${dark ? 30 : 18}%, transparent)` };
}

export function applyAccent(key) {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const a = accentFor(key, dark);
  const s = document.documentElement.style;
  s.setProperty("--accent", a.accent);
  s.setProperty("--on-accent", a.onAccent);
  s.setProperty("--accent-soft", a.soft);
}
