"""Shared browser helpers: scan any form into Jobsmith's field format, and fill fields robustly."""
from __future__ import annotations

import asyncio
import re
import sys

from playwright.async_api import Page, TimeoutError as PWTimeout


def browser_args(platform: str | None = None) -> list[str]:
    """Flags for every Chromium Jobsmith launches, so it never asks for your login keychain password ("Chromium Safe
    Storage" on macOS) or a Linux keyring. Playwright adds these itself; a direct launch doesn't."""
    platform = platform or sys.platform
    if platform == "darwin":
        return ["--use-mock-keychain"]
    if platform.startswith("linux"):
        return ["--password-store=basic"]
    return []

# Runs in the page. Returns every visible, fillable control with its human label.
SCAN_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return (r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none') || el.type === 'file'; };
  const clean = t => (t || '').replace(/\s+/g, ' ').replace(/\*\s*$/, '').trim();
  const labelFor = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    if (el.getAttribute('aria-labelledby')) {
      const t = el.getAttribute('aria-labelledby').split(/\s+/).map(i => document.getElementById(i)).filter(Boolean)
        .map(n => n.innerText).join(' '); if (clean(t)) return clean(t); }
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    const wrap = el.closest('label'); if (wrap) return clean(wrap.innerText);
    const fs = el.closest('fieldset'); if (fs && fs.querySelector('legend')) return clean(fs.querySelector('legend').innerText);
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
      const l = p.querySelector('label, legend, .application-label, [class*="label"]');
      if (l && !l.contains(el)) return clean(l.innerText);
    }
    return clean(el.placeholder || el.name || el.id);
  };
  // the section each field sits in ("Employment", "Education"), from the nearest heading above it
  const heads = [...document.querySelectorAll('h1, h2, h3, h4, legend, [role="heading"]')].filter(h => clean(h.innerText));
  const groupFor = el => { let g = ''; for (const h of heads) { if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) g = clean(h.innerText); else break; } return g.slice(0, 60); };
  const starred = el => { const l = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    return /\*\s*$/.test(((l || el.closest('label') || {}).innerText || '').trim()); };
  const out = []; const seenGroups = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (!vis(el) && type !== 'file') continue;
    const key = el.id ? `#${el.id}` : (el.name ? `[name="${el.name}"]` : null);
    if (!key) continue;
    if (type === 'radio' || type === 'checkbox') {
      const g = el.name || el.id; if (seenGroups.has(g)) continue;
      const group = el.name ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
      seenGroups.add(g);
      const fs = el.closest('fieldset'); const legend = fs && fs.querySelector('legend');
      let label = legend ? clean(legend.innerText) : '';
      if (!label) { let p = el.parentElement; for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
        const t = clean((p.innerText || '').split('\n')[0]); if (t && group.every(x => p.contains(x)) && t.length > 3) { label = t; break; } } }
      const opts = group.map(x => labelFor(x));
      out.push({ field: el.name ? `[name="${el.name}"]` : key, label: label || opts[0], value: group.some(x => x.checked) ? 'set' : '',
                 qtype: group.length > 1 ? (type === 'radio' ? 'radio' : 'multiselect') : 'checkbox',
                 required: group.some(x => x.required), options: group.length > 1 ? opts : [], description: '', group: groupFor(el) });
      continue;
    }
    const role = el.getAttribute('role');
    // a react-select shows its choice beside the input (which is empty): read what it shows
    const comboValue = () => { const c = el.closest('[class*=control]'); let t = c ? c.innerText : '';
      if (!c && el.parentElement) { const sv = el.parentElement.querySelector('[class*="single-value"], [class*="singleValue"]'); t = sv ? sv.innerText : ''; }
      t = clean(t); return /^select\b/i.test(t) ? '' : t; };
    out.push({ field: key, label: labelFor(el), value: type === 'file' ? (el.files && el.files.length ? 'file' : '') : (el.value || (role === 'combobox' ? comboValue() : '')),
      qtype: type === 'file' ? 'file' : el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : role === 'combobox' ? 'select' : 'text',
      required: el.required || el.getAttribute('aria-required') === 'true' || starred(el),
      options: el.tagName === 'SELECT' ? [...el.options].map(o => clean(o.text)).filter(t => t && !/^select|^--|^please/i.test(t)) : [],
      description: '', group: groupFor(el) });
  }
  // custom dropdowns (Workday and others): <button aria-haspopup="listbox">Select One</button>
  for (const el of document.querySelectorAll('button[aria-haspopup="listbox"], [role="button"][aria-haspopup="listbox"]')) {
    if (!vis(el)) continue;
    const auto = el.getAttribute('data-automation-id');
    const key = el.id ? `#${el.id}` : (auto ? `[data-automation-id="${auto}"]` : null);
    if (!key) continue;
    const txt = clean(el.innerText);
    out.push({ field: key, label: labelFor(el), qtype: 'listbox', value: /^select/i.test(txt) ? '' : txt,
               required: el.getAttribute('aria-required') === 'true' || /\*/.test(labelFor(el)), options: [], description: '', group: groupFor(el) });
  }
  return out;
}
"""


async def scan_form(page: Page) -> list[dict]:
    fields = await page.evaluate(SCAN_JS)
    seen, out = set(), []
    for f in fields:
        if f["field"] in seen or not f["label"]:
            continue
        seen.add(f["field"])
        f.setdefault("section", "main")
        out.append(f)
    return out


def css_for(field: str) -> str:
    if field.startswith(("#", "[")):
        if field.startswith("#"):
            return f'[id="{field[1:]}"]'
        return field
    return f'[id="{field}"], [name="{field}"]'


async def fill_text(page: Page, selector: str, value: str) -> bool:
    loc = page.locator(selector).first
    await loc.scroll_into_view_if_needed(timeout=5000)
    await loc.fill(value, timeout=8000)
    return (await loc.input_value()).strip() == value.strip()


def _best_option(texts: list[str], value: str) -> int | None:
    from ..classify import pick_option
    clean = [t for t in texts if t and t.lower() not in ("no options", "loading...")]
    if not clean:
        return None
    choice = pick_option(value, clean)
    if choice is None:
        w = value.strip().lower()
        choice = next((t for t in clean if t.lower().startswith(w) or w in t.lower()), None)
    return texts.index(choice) if choice is not None else None


# Finds the option list that belongs to one combobox. Pages often carry other, hidden
# [role=option] lists (Greenhouse's phone-country picker has ~240), so never search page-wide.
_OPTIONS_JS = r"""
(e) => {
  const vis = n => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ids = [e.getAttribute('aria-controls'), e.getAttribute('aria-owns'), e.id && `react-select-${e.id}-listbox`];
  let box = null;
  for (const id of ids) { if (id) { const n = document.getElementById(id); if (n && vis(n)) { box = n; break; } } }
  if (!box) {
    const ctl = e.closest('[class*="control"]');
    const root = ctl ? ctl.parentElement : e.parentElement;
    box = root && [...root.querySelectorAll('[class*="menu"], [role="listbox"]')].find(vis) || null;
  }
  if (!box) return { found: false, texts: [] };
  const opts = [...box.querySelectorAll('[role="option"], [class*="option"]')]
    .filter(o => vis(o) && !o.querySelector('[role="option"], [class*="option"]'));
  opts.forEach((o, i) => o.setAttribute('data-jobsmith-opt', String(i)));
  return { found: true, texts: opts.map(o => (o.innerText || '').trim()),
           loading: /loading/i.test(box.innerText || '') };
}
"""


async def _visible_options(page: Page, loc, timeout_ms: int) -> list[str]:
    """Wait for this combobox's own menu to show real options; returns their texts."""
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    texts: list[str] = []
    while asyncio.get_event_loop().time() < deadline:
        try:
            res = await loc.evaluate(_OPTIONS_JS)
        except Exception:
            res = {"found": False, "texts": []}
        texts = [t for t in res["texts"] if t and t.lower() not in ("no options", "loading...", "loading")]
        if texts and not res.get("loading"):
            await page.wait_for_timeout(150)
            res2 = await loc.evaluate(_OPTIONS_JS)
            t2 = [t for t in res2["texts"] if t and t.lower() not in ("no options", "loading...", "loading")]
            if t2 == texts:
                return texts
            texts = t2
        await page.wait_for_timeout(150)
    return texts


async def _open_combobox(page: Page, loc) -> None:
    """Focus the combobox by clicking its visible control (the input itself is a few pixels wide)."""
    await page.keyboard.press("Escape")  # close any menu left open by a previous field
    await loc.scroll_into_view_if_needed(timeout=5000)
    ctl = loc.locator('xpath=ancestor::*[contains(@class,"control")][1]')
    try:
        if await ctl.count():
            await ctl.first.click(timeout=4000)
        else:
            await loc.click(timeout=4000)
    except Exception:
        await loc.focus()


async def _clear_typed(page: Page, loc) -> None:
    """Remove typed filter text. Never press Backspace on an empty input: react-select would
    delete the current selection."""
    try:
        if not await loc.input_value(timeout=1000):
            return
    except Exception:
        return
    await page.keyboard.press("ControlOrMeta+a")
    await page.keyboard.press("Backspace")


async def fill_combobox(page: Page, selector: str, value: str, query: str | None = None,
                        wait_ms: int = 6000) -> bool:
    """React-select style comboboxes (Greenhouse's job boards and many others).
    Types `query` (default: the value) to filter, then clicks the best-matching option in
    this combobox's own menu. Leaves the field alone rather than guessing when nothing matches."""
    loc = page.locator(selector).first
    before = await combobox_text(page, selector)
    q = (query or value).strip()[:40]
    attempts = [q, q.split(",")[0].split("(")[0].split("/")[0].strip()[:20], ""]
    seen = set()
    for attempt in attempts:
        if attempt in seen:
            continue
        seen.add(attempt)
        await _open_combobox(page, loc)
        await _clear_typed(page, loc)
        if attempt:
            await page.keyboard.type(attempt, delay=25)
        else:
            await page.keyboard.press("ArrowDown")  # just open the full list
        texts = await _visible_options(page, loc, wait_ms)
        if not texts:
            continue
        idx = _best_option(texts, value)
        if idx is None:
            continue
        opt = page.locator(f'[data-jobsmith-opt="{idx}"]').first
        try:
            await opt.scroll_into_view_if_needed(timeout=2000)
            await opt.click(timeout=3000)
        except Exception:
            # fall back to keyboard: move the highlight down to the option and press Enter
            for _ in range(idx):
                await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(250)
        now = await combobox_text(page, selector)
        if now and now != before and not now.lower().startswith("select"):
            return True
        if texts[idx].lower() in now.lower():
            return True
    await _clear_typed(page, loc)
    await page.keyboard.press("Escape")
    return False


async def combobox_text(page: Page, selector: str) -> str:
    """What a react-select currently shows as selected."""
    try:
        return (await page.locator(selector).first.evaluate(
            "e => (e.closest('[class*=control]') || e.parentElement).innerText")).strip()
    except Exception:
        return ""


async def fill_select(page: Page, selector: str, value: str) -> bool:
    loc = page.locator(selector).first
    tag = (await loc.evaluate("e => e.tagName")).lower()
    if tag == "select":
        try:
            await loc.select_option(label=value, timeout=5000)
        except Exception:
            opts = await loc.evaluate("e => [...e.options].map(o => o.text.trim())")
            match = next((o for o in opts if o.lower() == value.lower()), None) or \
                next((o for o in opts if value.lower() in o.lower()), None)
            if not match:
                return False
            await loc.select_option(label=match, timeout=5000)
        return True
    return await fill_combobox(page, selector, value)


async def fill_choice(page: Page, selector: str, value: str | list[str]) -> bool:
    """Radio / checkbox groups: click the input whose label matches."""
    values = value if isinstance(value, list) else [v.strip() for v in re.split(r"[;\n]", value) if v.strip()]
    group = page.locator(selector)
    n = await group.count()
    ok = False
    for i in range(n):
        el = group.nth(i)
        label = await el.evaluate("""e => { const l = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
                                     return ((l && l.innerText) || (e.closest('label') && e.closest('label').innerText) ||
                                     e.value || '').trim(); }""")
        if any(v.lower() == label.lower() or (len(v) > 2 and v.lower() in label.lower()) for v in values):
            await el.check(force=True, timeout=5000)
            ok = True
    return ok


async def fill_listbox(page: Page, selector: str, value: str) -> bool:
    btn = page.locator(selector).first
    await btn.scroll_into_view_if_needed(timeout=5000)
    await btn.click(timeout=5000)
    opts = page.locator('[role="option"]')
    try:
        await opts.first.wait_for(timeout=5000)
    except PWTimeout:
        return False
    texts = [t.strip() for t in await opts.all_inner_texts()]
    idx = _best_option(texts, value)
    if idx is None:
        await page.keyboard.press("Escape")
        return False
    await opts.nth(idx).click()
    await page.wait_for_timeout(300)
    return True


async def fill_field(page: Page, selector: str, qtype: str, value: str, file_path: str | None = None) -> bool:
    if qtype == "listbox":
        return await fill_listbox(page, selector, value)
    if qtype == "file":
        if not file_path:
            return False
        await page.locator(selector).first.set_input_files(file_path, timeout=8000)
        return True
    if qtype in ("radio", "multiselect", "checkbox"):
        if qtype == "checkbox":
            if value.lower() in ("yes", "true", "checked", "i agree", "agree"):
                await page.locator(selector).first.check(force=True)
            return True
        loc = page.locator(selector)
        tag = (await loc.first.evaluate("e => e.tagName + ':' + (e.type||'')")).lower()
        if tag.startswith("input:checkbox") or tag.startswith("input:radio"):
            return await fill_choice(page, selector, value)
        return await fill_select(page, selector, value)
    if qtype == "select":
        return await fill_select(page, selector, value)
    loc = page.locator(selector).first
    role = await loc.get_attribute("role")
    if role == "combobox":
        return await fill_combobox(page, selector, value)
    return await fill_text(page, selector, value)


SUBMIT_SELECTORS = [
    'button[type="submit"]:has-text("Submit")', 'button:has-text("Submit application")',
    'button:has-text("Submit Application")', 'input[type="submit"]', 'button[type="submit"]',
]
CONFIRM_RE = re.compile(r"thank you for applying|application (has been )?(received|submitted)|"
                        r"we('ve| have) received your application|thanks for applying", re.I)


async def page_confirms_submission(page: Page) -> bool:
    try:
        if re.search(r"confirmation|thank", page.url, re.I):
            return True
        body = await page.locator("body").inner_text(timeout=3000)
        return bool(CONFIRM_RE.search(body))
    except Exception:
        return False


# "A verification code was sent to you@x.edu. ... enter the 8-character code to confirm you're a human."
CODE_RE = re.compile(r"(verification|security|confirmation) code (was|has been) (sent|emailed)|"
                     r"enter the \d+[- ]character code|enter (the|your) (verification|security) code", re.I)

# Finds the code box(es): Greenhouse uses one box per character; others use a single input.
_CODE_BOXES_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const lbl = e => ((e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)?.innerText) || '') + ' ' +
                   (e.getAttribute('aria-label') || '') + ' ' + (e.name || '') + ' ' + (e.id || '') + ' ' + (e.placeholder || '');
  const inputs = [...document.querySelectorAll('input')].filter(e => vis(e) && !['hidden','checkbox','radio','file','submit'].includes(e.type));
  let boxes = inputs.filter(e => /security|verification|one.?time|otp|passcode|code/i.test(lbl(e)) && !/zip|postal|country|promo/i.test(lbl(e)));
  const singles = boxes.filter(e => e.maxLength === 1);
  if (singles.length >= 4) boxes = singles;
  else if (!boxes.length) {
    // a run of one-character boxes next to each other
    const ones = inputs.filter(e => e.maxLength === 1);
    if (ones.length >= 4) boxes = ones;
  } else boxes = boxes.slice(0, 1);
  boxes.forEach((b, i) => b.setAttribute('data-jobsmith-code', String(i)));
  return boxes.length;
}
"""


async def security_code_prompt(page: Page) -> str:
    """If the page is asking for an emailed verification code, return its message (else '')."""
    try:
        body = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""
    m = CODE_RE.search(body)
    if not m:
        return ""
    try:
        if not await page.evaluate(_CODE_BOXES_JS):
            return ""
    except Exception:
        return ""
    start = body.rfind("\n", 0, m.start()) + 1
    end = body.find("\n", m.end())
    return " ".join(body[start:end if end != -1 else None].split())[:220]


async def enter_security_code(page: Page, code: str) -> bool:
    """Type a code you received into the code box(es). Jobsmith never reads your email for it."""
    code = re.sub(r"\s+", "", code)
    n = await page.evaluate(_CODE_BOXES_JS)
    if not n or not code:
        return False
    boxes = page.locator("[data-jobsmith-code]")
    if n == 1:
        await boxes.first.fill(code)
        return (await boxes.first.input_value()).strip() == code
    # one box per character: type into the first; most forms move focus along by themselves
    await boxes.first.click()
    await page.keyboard.type(code[:n], delay=40)
    vals = [await boxes.nth(i).input_value() for i in range(n)]
    if "".join(vals) == code[:n]:
        return True
    for i, ch in enumerate(code[:n]):
        await boxes.nth(i).fill(ch)
    vals = [await boxes.nth(i).input_value() for i in range(n)]
    return "".join(vals) == code[:n]


async def captcha_visible(page: Page) -> bool:
    for fr in page.frames:
        if re.search(r"recaptcha/.*/bframe|hcaptcha.*challenge|challenges\.cloudflare", fr.url):
            try:
                el = await fr.frame_element()
                if await el.is_visible():
                    return True
            except Exception:
                continue
    return False
