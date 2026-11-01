// In-app dialogs instead of the browser's alert/confirm/prompt, so they look the same everywhere.
// Each call shows one dialog and resolves with the answer (true/false, the typed text, or null when cancelled).
export const dlg = $state({ current: null });

function show(opts) {
  return new Promise((resolve) => { dlg.current = { ...opts, resolve }; });
}
export function answer(value) {
  const d = dlg.current;
  dlg.current = null;
  d?.resolve(value);
}

export const notice = (title, message = "") => show({ kind: "notice", title, message, ok: "OK" });
export const confirm = (title, message = "", ok = "OK", danger = false, cancel = "Cancel") =>
  show({ kind: "confirm", title, message, ok, danger, cancel });
export const askText = (title, message = "", value = "", ok = "OK") => show({ kind: "text", title, message, value, ok });
