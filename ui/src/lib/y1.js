// The nine official Y1 colours: body and wheel, sampled from Innioasis' product photos.
// The Y1 can't report its colour, so it's a preference; it also sets the app's accent.
export const Y1_COLORS = {
  black: ["Black", "#605f64", "#3f3f3f"],
  silver: ["Silver", "#adacb1", "#ececec"],
  blue: ["Blue", "#52c7be", "#e7eaee"],
  teal: ["Teal", "#afcec9", "#edecee"],
  pink: ["Pink", "#ecc4cc", "#dfe3e4"],
  purple: ["Purple", "#f2c2d6", "#e0dfdf"],
  orange: ["Orange", "#f7a374", "#f3eff0"],
  yellow: ["Yellow", "#f7c85e", "#eae9e9"],
  light_yellow: ["Light Yellow", "#f9ed7d", "#dddddd"],
};

const shade = (hex, f) =>
  "#" + [1, 3, 5].map((i) => Math.max(0, Math.min(255, Math.round(parseInt(hex.slice(i, i + 2), 16) * f)))
    .toString(16).padStart(2, "0")).join("");

// A flat drawing of the Y1 in its colour: body, screen with a menu, click wheel.
export function y1Svg(key) {
  const [, body, wheel] = Y1_COLORS[key] || Y1_COLORS.black;
  const ink = parseInt(wheel.slice(1, 3), 16) < 128 ? "#d8d8d8" : "#5a5a5e";
  const rows = [34, 41, 48, 55, 62, 69].map((y, i) =>
    `<rect x="18" y="${y}" width="${30 - (i * 5) % 12}" height="2.6" rx="1.3" fill="#a3a3a8"/>`).join("");
  return `<svg viewBox="0 0 120 190" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<rect x="2" y="2" width="116" height="186" rx="16" fill="${body}" stroke="${shade(body, 0.8)}" stroke-width="1.5"/>
<rect x="11" y="11" width="98" height="78" rx="6" fill="#161617"/>
<rect x="15" y="15" width="90" height="70" rx="2" fill="#f7f7f6"/>
<rect x="15" y="24" width="48" height="7" fill="${shade(body, 0.75)}"/>${rows}
<rect x="68" y="34" width="32" height="32" rx="2" fill="#dededc"/>
<circle cx="60" cy="137" r="40" fill="${wheel}" stroke="${shade(wheel, 0.85)}" stroke-width="1"/>
<circle cx="60" cy="137" r="15" fill="${body}" stroke="${shade(body, 0.8)}" stroke-width="1"/>
<g fill="${ink}"><rect x="54" y="105" width="12" height="2.4" rx="1.2"/>
<path d="M34 134v7l-5-3.5zM39 134v7l-5-3.5z"/><path d="M86 134v7l5-3.5zM81 134v7l5-3.5z"/>
<path d="M53 166v7l5.5-3.5z"/><rect x="61" y="166" width="2" height="7"/><rect x="65" y="166" width="2" height="7"/></g>
</svg>`;
}
