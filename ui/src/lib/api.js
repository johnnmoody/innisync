// Talking to the InniSync server (127.0.0.1). Errors carry the server's message and whether sign-in is needed.
export async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(j.error || r.statusText);
    e.status = r.status;
    e.signIn = !!j.signIn;
    throw e;
  }
  return j;
}

export async function upload(path, file) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

export const art = (id, size = 300) => `/art/${encodeURIComponent(id)}?size=${size}`;
export const devImg = (path) => `/devimg?path=${encodeURIComponent(path)}`;
