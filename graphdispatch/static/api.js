// Thin fetch wrapper. Errors carry the server's plain-language message.
export async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    const e = new Error("Could not reach the server. Check your connection and try again.");
    e.status = 0;
    throw e;
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = "Check the form: " + msg.map((m) => m.msg).join("; ");
    if (data && data.error) msg = data.error;
    const e = new Error(msg || `The request failed (${res.status}). Try again.`);
    e.status = res.status;
    throw e;
  }
  return data;
}
