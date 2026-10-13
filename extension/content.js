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

  // ------------------------------------------------------------------ the little panel
  let panel;
  function show(html, tone = "") {
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "jobsmith-panel";
      panel.attachShadow({ mode: "open" });
      document.documentElement.appendChild(panel);
    }
    panel.shadowRoot.innerHTML = `<style>
      .p{position:fixed;right:18px;bottom:18px;z-index:2147483647;font:14px/1.4 -apple-system,system-ui,Segoe UI,sans-serif;
         background:#fff;color:#1f2328;border:1px solid #d0d7de;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.15);
         padding:12px 14px;max-width:320px}
      .p.warn{border-color:#d4a72c} b{color:#1a5fb4} button{font:inherit;border:0;border-radius:6px;padding:7px 12px;cursor:pointer}
      .go{background:#1a5fb4;color:#fff} .x{background:none;color:#57606a;padding:4px 6px;float:right}
      ul{margin:6px 0 0 16px;padding:0} li{margin:2px 0} small{color:#57606a}
    </style><div class="p ${tone}"><button class="x" title="Hide">✕</button>${html}</div>`;
    panel.shadowRoot.querySelector(".x").onclick = () => { panel.remove(); panel = null; sessionStorage.setItem("jobsmith-hide", "1"); };
    panel.shadowRoot.querySelector(".go")?.addEventListener("click", fill);
    return panel.shadowRoot;
  }

  let busy = false;
  async function fill() {
    if (busy) return;
    busy = true;
    const fields = scan();
    show(`<b>Jobsmith</b> is reading ${fields.length} fields and writing answers…<br><small>Open questions take up to a minute.</small>`);
    const title = clean(document.querySelector("h1")?.innerText || document.title).slice(0, 200);
    const site = document.querySelector("meta[property='og:site_name']")?.content || "";
    const r = await send({ type: "answers", body: { url: location.href, title, site_name: site, fields } });
    if (!r.ok) {
      show(`<b>Jobsmith</b>: ${esc(r.error)}`, "warn"); busy = false; return;
    }
    const { answers, job_id, error } = r.data;
    let done = 0; const missing = []; let needAi = 0;
    for (const a of answers) {
      let ok = false;
      try { ok = await fillOne(a.id, a, job_id); } catch (_) { ok = false; }
      const f = fields.find(x => x.id === a.id);
      if (ok) done++;
      else if (f && f.required && !f.filled) { missing.push(f.label); if (a.kind === "generated" && !a.value) needAi++; }
      const el = els.get(a.id); const node = Array.isArray(el) ? el[0]?.closest("fieldset") || el[0] : el;
      if (node && !ok && f?.required) node.style.outline = "2px solid #d4a72c";
    }
    show(`<b>Filled ${done} of ${fields.length} fields.</b> Check it, then submit when you're ready.` +
         (missing.length ? `<br>Needs you:<ul>${missing.slice(0, 6).map(m => `<li>${esc(m.slice(0, 70))}</li>`).join("")}</ul>` : "") +
         (needAi ? `<br><small>${needAi} written answer${needAi > 1 ? "s need" : " needs"} an AI. Connect one in Jobsmith's Settings.</small>` :
          error ? `<br><small>${esc(error)}</small>` : ""), missing.length ? "warn" : "");
    busy = false;
  }

  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (msg.type === "fill") { fill(); reply({ ok: true }); }
    if (msg.type === "info") {
      const fields = scan();
      reply({ application: looksLikeApplication(fields), fields: fields.length, title: clean(document.querySelector("h1")?.innerText || document.title) });
    }
    return false;
  });

  // Offer to fill when this looks like an application form (once per page, dismissible).
  function offer() {
    if (window.top !== window && !document.querySelector("form")) return;
    if (sessionStorage.getItem("jobsmith-hide") || panel) return;
    const fields = scan();
    if (!looksLikeApplication(fields)) return;
    send({ type: "ping" }).then(r => {
      if (!r.ok) return;   // Jobsmith isn't running: stay quiet
      show(`<b>Jobsmith</b> can fill this application from your profile.<br><br><button class="go">Fill it (Alt+J)</button> <small>It won't submit.</small>`);
    });
  }
  setTimeout(offer, 1200);
  new MutationObserver(() => { clearTimeout(window.__jobsmithT); window.__jobsmithT = setTimeout(offer, 1500); })
    .observe(document.body, { childList: true, subtree: true });
})();
