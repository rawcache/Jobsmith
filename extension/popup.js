const $ = id => document.getElementById(id);
const send = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => res(r || { ok: false })));

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// Job sites whose frames the extension may reach on its own: the manifest's host_permissions (see SECURITY.md).
const JOB_SITES = /(^|\.)(greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com|icims\.com|smartrecruiters\.com)$/i;

// The page's own Jobsmith script. A tab opened before the extension was loaded (or reloaded) doesn't have one, so
// add it now: to the top page (opening this popup grants access to it), and to frames from the job sites above
// (company sites embed Greenhouse forms in a frame). A form in a frame from anywhere else needs a reload, which
// brings the script back everywhere.
async function pageScript(tab) {
  const ask = () => chrome.tabs.sendMessage(tab.id, { type: "info" }, { frameId: 0 });
  let info;
  try { info = await ask(); } catch (_) { /* not there yet */ }
  if (!info) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      info = await ask();
    } catch (_) {
      return null;                                   // chrome:// pages, the Web Store, PDFs
    }
  }
  let now = info;                                    // read afresh every time the popup opens
  // A job site's frame, or frames inside frames (a wrapper around one; what's inside can't be seen from here)
  if ((info.frames || []).some(h => JOB_SITES.test(h)) || info.nested) {
    // Chrome adds it only to the frames the extension may reach, at any depth; the others are skipped
    await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["content.js"] })
      .catch(() => { info.reload = true; });
    now = await ask().catch(() => info);             // which frames hold a form, now they can say
  }
  const unreached = h => !JOB_SITES.test(h);
  // A form was reached, so another site's frame beside it (a video, a map) isn't worth a reload.
  if (!info.application && !now.forms && (now.bare || []).some(unreached)) info.reload = true;
  // The page is an application itself (a talent-network box, say) but the real one is in another site's frame
  if (info.application && (now.bareApps || []).some(unreached)) info.reload = true;
  return info;
}

// Needs you, by fix: what held applications wait on, each once with how many it unblocks, answered right here.
// An answer goes to Jobsmith, which re-checks every held application and starts the complete ones within your
// limits. Everything shown comes from the engine and is put on the page as text, never as markup.
const SHOWN = 3;
const drafts = {};          // what you've typed, by fix: kept when an answer to another one redraws the list

function el(tag, props = {}, ...kids) {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids);
  return e;
}

function showFixes(d) {
  const list = d.fixes || [];
  $("needs").hidden = list.length === 0 && $("needs-said").hidden;   // what your last answer did stays shown
  $("fixes").replaceChildren(...list.slice(0, SHOWN).map(fixRow));
  $("needs-more").hidden = list.length <= SHOWN;
  $("needs-more").textContent = `${list.length - SHOWN} more in the dashboard.`;
}

function fixRow(f) {
  const count = f.kind === "resume_pdf" ? "blocks every application" : `unblocks ${f.unblocks}`;
  const row = el("li", { className: "fix" },
    el("div", { className: "fix-h" }, el("strong", { textContent: f.title }), el("span", { className: "count", textContent: count })));
  const answer = async (value, buttons) => {
    buttons.forEach(b => { b.disabled = true; });
    const r = await send({ type: "fix", body: { id: f.id, value } });
    buttons.forEach(b => { b.disabled = false; });
    const said = $("needs-said");
    said.hidden = false;
    if (!r.ok) { said.className = "result bad"; said.textContent = r.error; return; }
    if (drafts[f.id] === value) delete drafts[f.id];
    const n = r.data.freed.length, s = r.data.started.length;
    said.className = "result";
    said.textContent = r.data.note || (n === 0 ? "Saved. Nothing else was waiting on just that." :
      `Saved. ${n} application${n === 1 ? " has" : "s have"} nothing left${s ? `: ${s} going out now` : ""}.`);
    showFixes(r.data);
  };
  if (f.kind === "resume_pdf") {
    const b = el("button", { className: "primary", textContent: "Add it in the dashboard" });
    b.addEventListener("click", () => send({ type: "open", path: "/#/" }));
    row.append(b);
  } else if ((f.choices || []).length) {
    const buttons = f.choices.map(c => el("button", { textContent: c }));
    buttons.forEach((b, i) => b.addEventListener("click", () => answer(f.choices[i], buttons)));
    row.append(el("div", { className: "choices" }, ...buttons));
  } else {
    const box = f.kind === "essay"
      ? el("textarea", { rows: 4, value: drafts[f.id] ?? (f.value || ""), placeholder: "Your answer, in your words. {company} and {role} are filled in for each one." })
      : el("input", { value: drafts[f.id] ?? (f.value || ""), placeholder: "Your answer" });
    box.setAttribute("aria-label", f.title);
    const save = el("button", { className: "primary", textContent: f.kind === "essay" ? "Save your answer" : "Save" });
    const ready = () => { save.disabled = !box.value.trim(); };
    box.addEventListener("input", () => { drafts[f.id] = box.value; ready(); }); ready();
    save.addEventListener("click", () => answer(box.value, [save]));
    row.append(box, save);
  }
  return row;
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
  send({ type: "fixes" }).then(r => { if (r.ok) showFixes(r.data); });

  const tab = await activeTab();
  const info = await pageScript(tab);
  if (!info) {
    $("fill").disabled = true;
    $("fill").textContent = "Can't fill this page";
    return;
  }
  if (!info.application) $("fill").textContent = `Fill this page (${info.fields} fields)`;
  if (info.reload) {
    $("result").hidden = false;
    $("result").className = "result warn";
    $("result").textContent = "Reload this page to fill the form inside it.";
  }
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

// Done checking the page (the reload hint is shown, the panel asked to open): tests wait for this mark instead of
// guessing how long reaching every frame takes.
init().finally(() => { document.body.dataset.ready = "true"; });
