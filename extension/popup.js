const $ = id => document.getElementById(id);
const send = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => res(r || { ok: false })));

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function init() {
  const ping = await send({ type: "ping" });
  if (!ping.ok) {
    $("dot").className = "dot off";
    $("status").hidden = true;
    $("offline").hidden = false;
    return;
  }
  const p = ping.data;
  $("dot").className = "dot ok";
  $("status").textContent = p.resume
    ? `Connected. Writing with ${p.ai}${p.ai_ok ? "" : " (not ready)"}.`
    : "Connected. Add your resume PDF in Jobsmith first, so there's something to attach.";
  $("actions").hidden = false;

  const tab = await activeTab();
  let info = null;
  try { info = await chrome.tabs.sendMessage(tab.id, { type: "info" }); } catch (_) { /* no content script here (e.g. chrome:// pages) */ }
  if (!info) {
    $("fill").disabled = true;
    $("fill").textContent = "Can't fill this page";
  } else if (!info.application) {
    $("fill").textContent = `Fill this page (${info.fields} fields)`;
  }
}

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
