// Jobsmith on the page you're looking at: finds application forms, fills them from your Jobsmith
// profile (through the app on your computer), and never clicks Submit.
(() => {
  if (window.__jobsmith) return;
  window.__jobsmith = true;

  const clean = t => (t || "").replace(/\s+/g, " ").replace(/\*\s*$/, "").trim();
  const esc = t => String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const norm = t => clean(t).toLowerCase().replace(/[^a-z0-9 ]/g, "");
  const visible = el => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return (r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none") || el.type === "file";
  };
  const send = msg => new Promise(res => chrome.runtime.sendMessage(msg, r => res(r || { ok: false, error: chrome.runtime.lastError?.message })));

  // ------------------------------------------------------------------ reading the form
  function labelFor(el) {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    const by = el.getAttribute("aria-labelledby");
    if (by) { const t = by.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(n => n.innerText).join(" "); if (clean(t)) return clean(t); }
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    const wrap = el.closest("label"); if (wrap) return clean(wrap.innerText);
    const fs = el.closest("fieldset"); if (fs && fs.querySelector("legend")) return clean(fs.querySelector("legend").innerText);
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
      const l = p.querySelector("label, legend, .application-label, [class*='label']");
      if (l && !l.contains(el)) return clean(l.innerText);
    }
    return clean(el.placeholder || el.name || el.id);
  }

  // "First Name*": the asterisk marks a required field (labelFor strips it)
  const starred = el => {
    const l = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    return /\*\s*$/.test(((l || el.closest("label") || {}).innerText || "").trim());
  };

  let nextId = 1;
  const els = new Map();   // id -> element, or array of elements for radio/checkbox groups
  function tag(el) {
    if (!el.dataset.jobsmithId) el.dataset.jobsmithId = `js${nextId++}`;
    return el.dataset.jobsmithId;
  }

  function scan() {
    els.clear();
    const out = []; const groups = new Set();
    for (const el of document.querySelectorAll("input, textarea, select")) {
      const type = (el.type || el.tagName).toLowerCase();
      if (["hidden", "submit", "button", "image", "reset", "search", "password"].includes(type)) continue;
      if (!visible(el) && type !== "file") continue;
      if (type === "radio" || type === "checkbox") {
        const g = el.name || el.id; if (!g || groups.has(g)) continue; groups.add(g);
        const group = el.name ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
        const fs = el.closest("fieldset"); const legend = fs && fs.querySelector("legend");
        let label = legend ? clean(legend.innerText) : "";
        if (!label) { let p = el.parentElement; for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
          const t = clean((p.innerText || "").split("\n")[0]); if (t && t.length > 3 && group.every(x => p.contains(x))) { label = t; break; } } }
        const id = tag(el); els.set(id, group);
        out.push({ id, label: label || labelFor(el), type: group.length > 1 ? (type === "radio" ? "radio" : "multiselect") : "checkbox",
                   required: group.some(x => x.required), options: group.length > 1 ? group.map(labelFor) : [],
                   filled: group.some(x => x.checked) });
        continue;
      }
      const id = tag(el); els.set(id, el);
      const combo = el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete") === "list";
      out.push({ id, label: labelFor(el),
        type: type === "file" ? "file" : el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea" : combo ? "combobox" : "text",
        required: el.required || el.getAttribute("aria-required") === "true" || starred(el),
        options: el.tagName === "SELECT" ? [...el.options].map(o => clean(o.text)).filter(t => t && !/^select|^--|^please/i.test(t)) : [],
        filled: type === "file" ? !!(el.files && el.files.length) : !!el.value });
    }
    return out.filter(f => f.label);
  }

  function looksLikeApplication(fields) {
    if (fields.length < 3) return false;
    const text = fields.map(f => f.label.toLowerCase()).join(" | ");
    return /first name|full name|last name|email/.test(text) && (/resume|cv|phone|linkedin|cover letter/.test(text) || fields.length >= 6);
  }

  // ------------------------------------------------------------------ filling
  function setNative(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);   // React sees this as a user edit
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function inRange(options, value) {
    // "3.71" against "3.5 - 3.79", "Below 3.0", "4.0 and above"
    const x = parseFloat(String(value).replace(/[^0-9.]/g, "")); if (isNaN(x) || !/^\s*[\d.]+\s*$/.test(value)) return -1;
    return options.findIndex(o => {
      const n = (o.match(/\d+(\.\d+)?/g) || []).map(Number);
      if (n.length >= 2) return x >= n[0] && x <= n[1];
      if (n.length === 1 && /below|under|less/i.test(o)) return x < n[0];
      if (n.length === 1 && /above|over|more|\+/i.test(o)) return x >= n[0];
      return false;
    });
  }

  function best(options, value) {
    const v = norm(value); if (!v) return -1;
    const r = inRange(options, value); if (r >= 0) return r;
    const o = options.map(norm);
    let i = o.indexOf(v); if (i >= 0) return i;
    i = o.findIndex(x => x.startsWith(v) || v.startsWith(x) && x.length > 1); if (i >= 0) return i;
    if (/^(yes|no)$/.test(v)) { i = o.findIndex(x => x.split(" ")[0] === v || x.startsWith(v)); if (i >= 0) return i; }
    return o.findIndex(x => x.includes(v) || (v.length > 3 && v.includes(x)));
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function optionsNear(el) {
    // The field's own list: aria-controls, else the closest options to the field (pages often have other lists).
    const id = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    const box = id && document.getElementById(id);
    if (box) return [...box.querySelectorAll("[role='option']")].filter(visible);
    for (let p = el.parentElement, i = 0; p && i < 4; p = p.parentElement, i++) {
      const o = [...p.querySelectorAll("[role='option']")].filter(visible);
      if (o.length) return o;
    }
    return [...document.querySelectorAll("[role='option']")].filter(visible);
  }

  async function pick(el, value, waitMs) {
    for (let t = 0; t < waitMs / 200; t++) {
      await sleep(200);
      const opts = optionsNear(el);
      if (opts.length) {
        const i = best(opts.map(o => o.innerText), value);
        if (i >= 0) { opts[i].scrollIntoView({ block: "nearest" }); opts[i].click(); return true; }
        return false;
      }
    }
    return false;
  }

  async function fillCombobox(el, value) {
    el.focus(); el.click();
    // 1) open the full list and pick (works for ranges like GPA buckets)
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", code: "ArrowDown", bubbles: true }));
    if (await pick(el, value, 800)) return true;
    // 2) type to search: the whole answer, then its first words (long lists like schools and cities)
    for (const q of [value, value.split(/[,(]/)[0], value.split(" ").slice(0, 2).join(" ")]) {
      setNative(el, q);
      if (await pick(el, value, 2500)) return true;
    }
    setNative(el, "");
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return false;
  }

  async function attach(el, kind, jobId) {
    const f = await send({ type: "file", kind, job_id: jobId });
    if (!f.ok) return false;
    const bytes = Uint8Array.from(atob(f.b64), c => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], f.name, { type: f.type }));
    el.files = dt.files;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  async function fillOne(id, a, jobId) {
    const target = els.get(id);
    if (!target) return false;
    if (a.file) return attach(target, a.file, jobId);
    const value = (a.value || "").trim();
    if (!value) return false;
    if (Array.isArray(target)) {
      if (target.length === 1) {
        const want = /^(yes|true|i agree|agree|checked)/i.test(value);
        if (want !== target[0].checked) target[0].click();
        return true;
      }
      const wanted = value.split(/\s*[;,]\s*/);
      let any = false;
      for (const w of wanted) {
        const i = best(target.map(labelFor), w);
        if (i >= 0) { if (!target[i].checked) target[i].click(); any = true; }
      }
      return any;
    }
    if (target.tagName === "SELECT") {
      const texts = [...target.options].map(o => o.text);
      const i = best(texts, value); if (i < 0) return false;
      target.selectedIndex = i;
      target.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    if (target.getAttribute("role") === "combobox" || target.getAttribute("aria-autocomplete") === "list") return fillCombobox(target, value);
    if (target.value && target.value.trim()) return true;   // never overwrite what you typed
    setNative(target, value);
    return true;
  }

  // ------------------------------------------------------------------ the side panel
  // On a job posting or application: the role, how your resume matches, who you know there, Autofill,
  // and the cover letter. Folds into a small tab on the right edge. Shadow DOM, so the site's CSS can't touch it.
  const ATS = /greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com|smartrecruiters\.com|workable\.com|icims\.com|jobvite\.com|rippling\.com|eightfold\.ai|oraclecloud\.com|taleo\.net|successfactors/i;
  const MARK = ["...........##...","..........##....",".........##.....","...####.##......","...######.......","...####.........",
    "################",".###############","..##############","......########..",".......######...","......########..","....############"];
  const mark = (px = 18) => `<svg width="${px}" height="${px * 13 / 16}" viewBox="0 0 64 52" fill="currentColor">${MARK.map((r, y) => [...r].map((c, x) => c === "#" ? `<rect x="${x * 4}" y="${y * 4}" width="3" height="3"/>` : "").join("")).join("")}</svg>`;
  const PANEL_CSS = `
    :host{all:initial}
    .wrap{position:fixed;top:72px;right:0;z-index:2147483647;font:13px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;color:#16161d}
    .tab{display:flex;flex-direction:column;align-items:center;gap:6px;padding:10px 6px;background:#f2f0ec;border:1px solid #d9d4ca;border-right:0;
      border-radius:10px 0 0 10px;box-shadow:0 6px 20px rgba(22,22,29,.12);cursor:pointer;color:#c2410c}
    .tab span{writing-mode:vertical-rl;font:600 11px ui-monospace,"SF Mono",Menlo,monospace;color:#16161d;letter-spacing:.02em}
    .tab b{font:600 10px ui-monospace,monospace;background:#c2410c;color:#fff;border-radius:8px;padding:1px 5px}
    .p{width:330px;max-height:calc(100vh - 96px);overflow:auto;background:#f2f0ec;border:1px solid #d9d4ca;border-right:0;border-radius:12px 0 0 12px;
      box-shadow:0 10px 32px rgba(22,22,29,.16)}
    .h{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #e0dcd4;color:#c2410c;position:sticky;top:0;background:#f2f0ec}
    .h strong{font:600 13px ui-monospace,"SF Mono",Menlo,monospace;color:#16161d;flex:1}
    .h button{border:0;background:none;color:#75716a;cursor:pointer;font-size:16px;padding:2px 6px;border-radius:5px}
    .h button:hover{background:#e8e4dc;color:#16161d}
    .sec{padding:12px;border-bottom:1px solid #e0dcd4}
    .sec:last-child{border-bottom:0}
    .job{background:#fbfaf8;border:1px solid #e0dcd4;border-radius:10px;padding:10px 12px}
    .job .t{font-weight:600;font-size:14px;line-height:1.3}
    .muted{color:#75716a}.small{font-size:12px}.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
    .lbl{font:500 11.5px ui-monospace,"SF Mono",Menlo,monospace;color:#75716a;margin:0 0 6px}
    .go{display:block;width:100%;border:0;border-radius:8px;padding:10px;background:#c2410c;color:#fff;font:600 14px -apple-system,system-ui,sans-serif;cursor:pointer}
    .go:hover{background:#9a3412}.go:disabled{opacity:.6;cursor:default}
    .btn{border:1px solid #cfc9bf;background:#fbfaf8;border-radius:6px;padding:5px 10px;font:500 12.5px -apple-system,system-ui,sans-serif;color:#16161d;cursor:pointer}
    .btn:hover{background:#efece6}
    a{color:#16161d}
    .ring{--p:0;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;flex:none;background:conic-gradient(var(--c) calc(var(--p)*1%),#e0dcd4 0)}
    .ring b{display:grid;place-items:center;width:40px;height:40px;border-radius:50%;background:#f2f0ec;font:600 14px ui-monospace,monospace}
    .row{display:flex;gap:10px;align-items:center}
    .kw{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}.kw span{font:11px ui-monospace,monospace;padding:1px 6px;border-radius:4px;background:#e8e4dc}
    .kw span.miss{background:transparent;border:1px dashed #cfc9bf;color:#75716a}
    ul{list-style:none;margin:0;padding:0}li{margin:4px 0}
    .note{background:#fbeee4;border:1px solid #f3c9a8;border-radius:8px;padding:8px 10px;margin-top:8px}
    .warn{background:#fbf3dc;border-color:#ecd9a0}
    .ok{color:#15803d;font-weight:600}
    .left .tab{border-right:1px solid #d9d4ca;border-left:0;border-radius:0 10px 10px 0}
    .left .p{border-right:1px solid #d9d4ca;border-left:0;border-radius:0 12px 12px 0}
  `;
  let host, root, state = { open: true, ctx: null, msg: "", tone: "", similar: null };
  const isPosting = () => ATS.test(location.host) || !!document.querySelector('script[type="application/ld+json"]')?.textContent?.includes('"JobPosting"')
    || looksLikeApplication(scan());

  // Other extensions fold into tabs on the right edge too (Simplify's sits there). Jobsmith's tab goes where nothing
  // else floats, so it never covers theirs and theirs never covers it.
  function floatsAt(x, y) {
    // Look through the whole stack: page content can sit over another extension's tab and still hide it.
    for (const el of document.elementsFromPoint(x, y)) {
      if (el === host || el === document.documentElement || el === document.body) continue;
      const r = el.getBoundingClientRect();
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) return true;   // drawn from inside a shadow root
      if (r.width > innerWidth / 2 && r.height > innerHeight / 2) continue;      // a page-sized layer, not a tab
      for (let p = el; p && p !== document.body; p = p.parentElement)
        if (/fixed|sticky/.test(getComputedStyle(p).position)) return true;
    }
    return false;
  }
  function freeSpot(w, h) {
    const clear = (side, top) => [4, w / 2, w - 4].every(dx => {
      const x = side === "right" ? innerWidth - dx : dx;
      for (let y = top; y <= top + h; y += 10) if (floatsAt(x, Math.min(y, innerHeight - 1))) return false;
      return true;
    });
    for (const side of ["right", "left"])
      for (let top = 72; top + h <= innerHeight - 8; top += 20) if (clear(side, top)) return { side, top };
    return { side: "right", top: 72 };
  }
  function place() {
    if (!host) return;
    if (host.parentNode !== document.documentElement || host.nextElementSibling) document.documentElement.appendChild(host);
    const wrap = root.querySelector(".wrap"), tab = root.querySelector(".tab");
    if (!wrap) return;
    const r = tab ? tab.getBoundingClientRect() : { width: 330, height: 120 };
    if (tab) state.spot = freeSpot(r.width, r.height);
    const s = state.spot || { side: "right", top: 72 };
    wrap.classList.toggle("left", s.side === "left");
    wrap.style.top = `${tab ? s.top : 72}px`;          // the open panel starts high so all of it fits
    wrap.style.right = s.side === "right" ? "0" : "auto";
    wrap.style.left = s.side === "left" ? "0" : "auto";
  }

  function render() {
    if (!host) {
      host = document.createElement("div"); host.id = "jobsmith-panel";
      root = host.attachShadow({ mode: "open" }); document.documentElement.appendChild(host);
    }
    const c = state.ctx;
    if (!state.open) {
      root.innerHTML = `<style>${PANEL_CSS}</style><div class="wrap"><div class="tab" title="Open Jobsmith">${mark(16)}<span>jobsmith</span>${c && c.people_total ? `<b>${c.people_total}</b>` : ""}</div></div>`;
      root.querySelector(".tab").onclick = () => { state.open = true; chrome.storage.local.set({ panelOpen: true }); render(); };
      place();
      return;
    }
    const m = c?.match || {}; const score = m.score ?? null;
    const color = score == null ? "#cfc9bf" : score >= 60 ? "#15803d" : score >= 35 ? "#d97706" : "#b91c1c";
    root.innerHTML = `<style>${PANEL_CSS}</style><div class="wrap"><div class="p">
      <div class="h">${mark(18)}<strong>jobsmith</strong><button class="fold" title="Fold away">›</button></div>
      ${state.similar ? submittedHtml() : ""}
      ${c ? `<div class="sec"><div class="job"><div class="t">${esc(c.title || document.title)}</div>
        <div class="muted small">${esc(c.company || "")}${c.location ? `, ${esc(c.location)}` : ""}</div>
        ${c.pay ? `<div class="mono small" style="margin-top:4px">${esc(c.pay)}</div>` : ""}
        ${c.status === "submitted" ? `<div class="ok small" style="margin-top:6px">Applied</div>` : c.fit != null ? `<div class="small muted mono" style="margin-top:6px">fit ${Math.round(c.fit)}</div>` : ""}</div></div>` : ""}
      <div class="sec"><button class="go fill">Autofill this page</button>
        <p class="small muted" style="margin:6px 0 0">From your Jobsmith profile. It never submits. (Alt+J)</p>
        ${state.msg ? `<div class="note ${state.tone}">${state.msg}</div>` : ""}</div>
      ${c && c.people_total ? `<div class="sec"><p class="lbl">You know ${c.people_total} ${c.people_total === 1 ? "person" : "people"} here</p><ul>
        ${c.people.map(p => `<li><a href="${esc(p.url || "#")}" target="_blank" rel="noreferrer">${esc(p.name)}</a><div class="small muted">${esc(p.position || "")}</div></li>`).join("")}</ul>
        <p class="small" style="margin:8px 0 0"><a href="#" class="outreach">Draft a referral ask</a></p></div>` : ""}
      ${score != null ? `<div class="sec"><p class="lbl">Resume match</p><div class="row"><span class="ring" style="--p:${score};--c:${color}"><b>${score}</b></span>
        <div class="small">${m.matched.length} of ${m.total} skills this posting asks for are on your resume.</div></div>
        <div class="kw">${m.matched.map(k => `<span>${esc(k)}</span>`).join("")}${m.missing.map(k => `<span class="miss">${esc(k)}</span>`).join("")}</div></div>` : ""}
      <div class="sec"><p class="lbl">Cover letter</p><div class="row">
        ${c && c.cover_letter ? `<button class="btn letter-open">Open it</button>` : `<button class="btn letter-write">Write one</button>`}
        <span class="small muted">${c && c.cover_letter ? "Attached when a field asks." : "From your resume, for this role."}</span></div></div>
      <div class="sec row"><button class="btn save">${c && c.known ? "Open in Jobsmith" : "Save to Jobsmith"}</button>
        ${c && c.known && c.status !== "submitted" ? `<button class="btn auto">Let autopilot apply</button>` : ""}</div>
    </div></div>`;
    place();
    root.querySelector(".fold").onclick = () => { state.open = false; chrome.storage.local.set({ panelOpen: false }); render(); };
    root.querySelector(".fill").onclick = fill;
    root.querySelector(".outreach")?.addEventListener("click", e => { e.preventDefault(); send({ type: "open", path: `/#/outreach/${encodeURIComponent(c.company)}` }); });
    root.querySelector(".letter-open")?.addEventListener("click", () => send({ type: "open", path: `/api/jobs/${c.job_id}/cover-letter.pdf` }));
    root.querySelector(".letter-write")?.addEventListener("click", async () => {
      say("Writing your cover letter…");
      const s = await send({ type: "save", body: { url: location.href, title: pageTitle(), site_name: site() } });
      if (!s.ok) return say(esc(s.error), "warn");
      const r = await send({ type: "cover", job_id: s.data.job_id });
      say(r.ok ? "Written. Open it to read or edit." : esc(r.error), r.ok ? "" : "warn"); await load();
    });
    root.querySelector(".save").onclick = async () => {
      if (c && c.known) return send({ type: "open", path: `/#/job/${c.job_id}` });
      const r = await send({ type: "save", body: { url: location.href, title: pageTitle(), site_name: site() } });
      say(r.ok ? `Saved: ${esc(r.data.company)}, ${esc(r.data.title)}.` : esc(r.error), r.ok ? "" : "warn"); await load();
    };
    root.querySelector(".auto")?.addEventListener("click", async () => {
      const r = await send({ type: "save", body: { url: location.href, title: pageTitle(), site_name: site(), apply: true } });
      say(r.ok && r.data.started ? "Autopilot is applying. Watch it in Jobsmith." : esc(r.error || "Couldn't start it."), r.ok ? "" : "warn");
    });
  }
  function submittedHtml() {
    const s = state.similar;
    return `<div class="sec"><div class="note"><span class="ok">Application submitted.</span> Logged to Applications in Jobsmith.</div>
      ${s.similar.length ? `<p class="lbl" style="margin-top:10px">Similar roles</p><ul>${s.similar.map(j =>
        `<li><a href="#" data-job="${esc(j.id)}" class="sim">${esc(j.company)}: ${esc(j.title)}</a></li>`).join("")}</ul>` : ""}</div>`;
  }
  const say = (msg, tone = "") => { state.msg = msg; state.tone = tone; render(); };
  const pageTitle = () => clean(document.querySelector("h1")?.innerText || document.title).slice(0, 200);
  const site = () => document.querySelector("meta[property='og:site_name']")?.content || "";

  async function load() {
    const r = await send({ type: "context", body: { url: location.href, title: pageTitle(), site_name: site(), text: (document.body.innerText || "").slice(0, 20000) } });
    if (!r.ok) return false;
    state.ctx = r.data; render();
    root.querySelectorAll(".sim").forEach(a => a.addEventListener("click", e => { e.preventDefault(); send({ type: "open", path: `/#/job/${a.dataset.job}` }); }));
    return true;
  }

  let busy = false;
  async function fill() {
    if (busy) return;
    busy = true; state.open = true;
    const fields = scan();
    say(`Reading ${fields.length} fields and writing answers… Open questions take up to a minute.`);
    const r = await send({ type: "answers", body: { url: location.href, title: pageTitle(), site_name: site(), fields } });
    if (!r.ok) { say(esc(r.error), "warn"); busy = false; return; }
    const { answers, job_id, error, resume } = r.data;
    let done = 0; const missing = []; let needAi = 0; let noPdf = false;
    for (const a of answers) {
      let ok = false;
      const f = fields.find(x => x.id === a.id);
      if (a.file === "resume" && !resume) noPdf = true;      // no resume PDF yet: skip the upload, fill the rest
      else try { ok = await fillOne(a.id, a, job_id); } catch (_) { ok = false; }
      if (ok) done++;
      else if (a.file === "resume" && !resume) { /* said once below */ }
      else if (f && f.required && !f.filled) { missing.push(f.label); if (a.kind === "generated" && !a.value) needAi++; }
      const el = els.get(a.id); const node = Array.isArray(el) ? el[0]?.closest("fieldset") || el[0] : el;
      if (node && !ok && f?.required) node.style.outline = "2px solid #d97706";
    }
    say(`<b>Filled ${done} of ${fields.length} fields.</b> Check it, then submit when you're ready.` +
      (noPdf ? `<br>Add your resume PDF to attach it (Profile → PDF employers get, in Jobsmith).` : "") +
      (missing.length ? `<br>Needs you:<ul style="margin:4px 0 0 14px;list-style:disc">${missing.slice(0, 6).map(m => `<li>${esc(m.slice(0, 70))}</li>`).join("")}</ul>` : "") +
      (needAi ? `<br><span class="small">${needAi} written answer${needAi > 1 ? "s need" : " needs"} an AI. Connect one in Jobsmith's Settings.</span>` :
       error ? `<br><span class="small">${esc(error)}</span>` : ""), missing.length || noPdf ? "warn" : "");
    busy = false; load();
  }

  // ------------------------------------------------------------------ "Write with Jobsmith" beside each open question
  function addWriteButtons() {
    for (const el of document.querySelectorAll("textarea")) {
      if (el.dataset.jobsmithWrite || !visible(el) || el.closest("#jobsmith-panel")) continue;
      const label = labelFor(el);
      if (!label || label.length < 12) continue;
      el.dataset.jobsmithWrite = "1";
      const b = document.createElement("div");
      const sr = b.attachShadow({ mode: "open" });
      sr.innerHTML = `<style>button{display:inline-flex;align-items:center;gap:6px;margin:6px 0 2px;border:1px solid #d9d4ca;background:#f2f0ec;color:#16161d;
        border-radius:7px;padding:5px 10px;font:500 12.5px -apple-system,system-ui,sans-serif;cursor:pointer}button:hover{border-color:#c2410c}
        svg{color:#c2410c}span{font:12px -apple-system,system-ui,sans-serif;color:#75716a;margin-left:8px}</style>
        <button>${mark(13)}Write with Jobsmith</button><span></span>`;
      const btn = sr.querySelector("button"), note = sr.querySelector("span");
      btn.onclick = async (e) => {
        e.preventDefault();
        if (el.value.trim() && !confirmReplace(note)) return;
        btn.disabled = true; note.textContent = "Writing from your resume…";
        const limit = parseInt(el.getAttribute("maxlength") || "0", 10) || 0;
        const help = clean(el.closest("div")?.innerText || "").slice(0, 500);
        const r = await send({ type: "generate", body: { url: location.href, label, title: pageTitle(), site_name: site(), description: help, limit } });
        btn.disabled = false;
        if (!r.ok || !r.data.text) {
          const e = r.ok ? (r.data.error || "") : r.error;
          note.textContent = /disabled|no ai|not connected|NoLLM/i.test(e) || (r.ok && !e) ? "No AI connected. Pick one in Jobsmith's Settings (Gemini is free)." : e;
          return;
        }
        setNative(el, r.data.text);
        note.textContent = r.data.based_on.length ? `Based on: ${r.data.based_on.join(", ")}. Edit freely.` : "Edit freely.";
      };
      el.insertAdjacentElement("afterend", b);
    }
  }
  function confirmReplace(note) {
    if (note.dataset.armed) { delete note.dataset.armed; return true; }
    note.dataset.armed = "1"; note.textContent = "This replaces what's there. Click again to write.";
    return false;
  }

  // ------------------------------------------------------------------ noticing a submission
  // When you press Submit and the page then thanks you, log it to Applications (and suggest similar roles).
  const THANKS = /thank you for (applying|your application|submitting)|application (has been )?(submitted|received)|we('ve| have) received your application|thanks for applying|successfully (submitted|applied)/i;
  document.addEventListener("click", e => {
    const b = e.target.closest && e.target.closest("button, input[type=submit], a[role=button]");
    if (!b || b.closest("#jobsmith-panel")) return;
    const t = (b.innerText || b.value || "").trim();
    if (/^(submit|submit application|apply|send application|finish)/i.test(t))
      sessionStorage.setItem("jobsmith-submit", JSON.stringify({ url: location.href, title: pageTitle(), at: Date.now() }));
  }, true);
  async function checkThanks() {
    const raw = sessionStorage.getItem("jobsmith-submit"); if (!raw) return;
    const p = JSON.parse(raw);
    if (Date.now() - p.at > 10 * 60 * 1000) { sessionStorage.removeItem("jobsmith-submit"); return; }
    if (!THANKS.test((document.body.innerText || "").slice(0, 20000))) return;
    sessionStorage.removeItem("jobsmith-submit");
    const r = await send({ type: "submitted", body: { url: p.url, title: p.title, site_name: site() } });
    if (r.ok) { state.similar = r.data; state.msg = ""; state.open = true; render(); load(); }
  }

  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (msg.type === "fill") { fill(); reply({ ok: true }); }
    if (msg.type === "open" && window.top === window) { openPanel(); reply({ ok: true }); }
    if (msg.type === "info") {
      const fields = scan();
      reply({ application: looksLikeApplication(fields), fields: fields.length, title: pageTitle() });
    }
    return false;
  });

  function openPanel() {
    state.open = true; chrome.storage.local.set({ panelOpen: true });
    const fresh = !host;
    render();
    if (fresh) { load(); addWriteButtons(); checkThanks(); }
  }

  async function start() {
    if (window.top !== window) return;               // the panel lives in the top page only
    if (!isPosting()) return;
    const ping = await send({ type: "ping" });
    if (!ping.ok) return;                            // Jobsmith isn't running: stay out of the way
    const { panelOpen } = await chrome.storage.local.get("panelOpen");
    state.open = panelOpen !== false;
    if (host) return;                                // the popup opened it while we were asking
    render(); load(); addWriteButtons(); checkThanks();
    for (const ms of [1500, 4000]) setTimeout(place, ms);   // other extensions add their tabs a moment later
  }
  setTimeout(start, 900);
  addEventListener("resize", () => place());
  new MutationObserver(() => {
    clearTimeout(window.__jobsmithT);
    window.__jobsmithT = setTimeout(() => { if (host) { place(); addWriteButtons(); checkThanks(); } else start(); }, 1200);
  }).observe(document.body, { childList: true, subtree: true });
})();
