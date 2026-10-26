const $ = id => document.getElementById(id);
const send = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => res(r || { ok: false })));

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// The page's own Jobsmith script. A tab opened before the extension was loaded (or reloaded) doesn't have one,
// so add it now: opening this popup grants access to the tab.
async function pageScript(tab) {
  const ask = () => chrome.tabs.sendMessage(tab.id, { type: "info" }, { frameId: 0 });
  try { return await ask(); } catch (_) { /* not there yet */ }
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    return await ask();
  } catch (_) {
    return null;                                     // chrome:// pages, the Web Store, PDFs
  }
}

async function init() {
  const { applyWithAutopilot } = await chrome.storage.local.get("applyWithAutopilot");
  $("apply").checked = applyWithAutopilot === true;

  const ping = await send({ type: "ping" });
  if (!ping.ok) {
    $("dot").className = "dot off";
    $("status").hidden = true;
    $("offline").hidden = false;
    return;
  }
  const p = ping.data;
  $("dot").className = "dot ok";
  $("status").textContent = `Connected. Writing with ${p.ai}${p.ai_ok ? "" : " (not ready)"}.` +
    (p.resume ? "" : " Add your resume PDF to attach it; everything else still fills.");
  $("actions").hidden = false;

  const tab = await activeTab();
  const info = await pageScript(tab);
  if (!info) {
    $("fill").disabled = true;
    $("fill").textContent = "Can't fill this page";
    return;
  }
  if (!info.application) $("fill").textContent = `Fill this page (${info.fields} fields)`;
  chrome.tabs.sendMessage(tab.id, { type: "open" }, { frameId: 0 }).catch(() => {});   // the full panel, on the page
}

$("apply").addEventListener("change", () => chrome.storage.local.set({ applyWithAutopilot: $("apply").checked }));

$("fill").addEventListener("click", async () => {
  const tab = await activeTab();
  await chrome.tabs.sendMessage(tab.id, { type: "fill" }).catch(() => {});
  window.close();
});

$("save").addEventListener("click", async () => {
  const tab = await activeTab();
  $("save").disabled = true;
  $("save").textContent = "Sending…";
  const r = await send({ type: "save", body: { url: tab.url, title: tab.title, apply: $("apply").checked } });
  $("save").disabled = false;
  $("save").textContent = "Send this job to Jobsmith";
  const out = $("result");
  out.hidden = false;
  if (!r.ok) { out.className = "result warn"; out.textContent = r.error; return; }
  const d = r.data;
  const el = d.eligibility || {};
  out.className = "result" + (el.ok === false ? " warn" : "");
  out.textContent = `${d.company}: ${d.title}. ` +
    (d.fit != null ? `Fit ${d.fit}. ` : "") +
    (el.ok === false ? `You may not qualify (${(el.reasons || []).join(" ")}). ` : "") +
    (d.started ? "Autopilot is applying." : "Saved to your matches.");
});

$("dash").addEventListener("click", e => { e.preventDefault(); send({ type: "open", path: "/" }); });

init();
