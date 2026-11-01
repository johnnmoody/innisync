// Talking to the InniSync server (127.0.0.1). Errors carry the server's message and whether sign-in is needed.
export async function api(path, body) {
  // X-InniSync: the server only answers API calls that carry it (see server.py _allowed)
  const r = await fetch(path, body === undefined ? { headers: { "X-InniSync": "1" } } : {
    method: "POST", headers: { "Content-Type": "application/json", "X-InniSync": "1" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(j.error || r.statusText);
    e.status = r.status;
    e.signIn = !!j.signIn;
    e.code = j.code || null;   // e.g. "manifest": the Y1's sync record needs rebuilding
    throw e;
  }
  return j;
}

export async function upload(path, file) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-InniSync": "1" }, body: file });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

export const art = (id, size = 300) => `/art/${encodeURIComponent(id)}?size=${size}`;
export const devImg = (path) => `/devimg?path=${encodeURIComponent(path)}`;
