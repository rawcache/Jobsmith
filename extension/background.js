// Talks to the Jobsmith engine on this computer. Content scripts can't reach 127.0.0.1 from a website,
// so every request goes through here. Nothing is stored in the extension except the engine's address.

const DEFAULT_ENGINE = "http://127.0.0.1:8765";

async function engine() {
  const { engine } = await chrome.storage.local.get("engine");
  return (engine || DEFAULT_ENGINE).replace(/\/$/, "");
}

async function call(path, opts = {}) {
  const base = await engine();
  let r;
  try {
    r = await fetch(base + path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    });
  } catch (e) {
    return { ok: false, offline: true, error: "Jobsmith isn't running. Open a terminal and run: jobsmith" };
  }
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) { /* not JSON */ }
    return { ok: false, error: String(detail) };
  }
  return { ok: true, data: await r.json() };
}

async function file(kind, jobId) {
  const base = await engine();
  try {
    const r = await fetch(`${base}/api/ext/file/${kind}?job_id=${encodeURIComponent(jobId || "")}`);
    if (!r.ok) return { ok: false, error: (await r.json().catch(() => ({}))).detail || "No file" };
    const buf = new Uint8Array(await r.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return { ok: true, name: r.headers.get("X-Filename") || "resume.pdf", type: r.headers.get("Content-Type") || "application/pdf", b64: btoa(bin) };
  } catch (e) {
    return { ok: false, offline: true, error: "Jobsmith isn't running." };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.type === "ping") return reply(await call("/api/ext/ping"));
    if (msg.type === "answers") return reply(await call("/api/ext/answers", { method: "POST", body: JSON.stringify(msg.body) }));
    if (msg.type === "save") return reply(await call("/api/ext/save", { method: "POST", body: JSON.stringify(msg.body) }));
    if (msg.type === "file") return reply(await file(msg.kind, msg.job_id));
    if (msg.type === "context") return reply(await call("/api/ext/context", { method: "POST", body: JSON.stringify(msg.body) }));
    if (msg.type === "generate") return reply(await call("/api/ext/generate", { method: "POST", body: JSON.stringify(msg.body) }));
    if (msg.type === "submitted") return reply(await call("/api/ext/submitted", { method: "POST", body: JSON.stringify(msg.body) }));
    if (msg.type === "cover") return reply(await call(`/api/jobs/${encodeURIComponent(msg.job_id)}/cover-letter`, { method: "POST" }));
    if (msg.type === "open") { chrome.tabs.create({ url: (await engine()) + (msg.path || "/") }); return reply({ ok: true }); }
    reply({ ok: false, error: "unknown message" });
  })();
  return true; // async reply
});

// Alt+J fills the page you're on.
chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== "fill") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "fill" }).catch(() => {});
});
