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
  const clean = t => (t || '').replace(/\s+/g, ' ').replace(/[*✱]\s*$/, '').trim();   // ✱: Lever's required mark
  // a <label> wrapping its control: its text without the part that holds the control, so a dropdown's options or
  // an upload button's words ("ATTACH RESUME/CV") aren't read as the question (Lever wraps every question this way).
  // When that part holds the words too (<label><span>Email <input></span></label>), that part's words.
  const text = n => n.nodeType === 3 ? n.textContent : (n.innerText || '');
  const own = (wrap, el) => { let box = el; while (box.parentElement && box.parentElement !== wrap) box = box.parentElement;
    const rest = [...wrap.childNodes].filter(n => n !== box).map(text).join(' ');
    if (clean(rest) || box === el) return rest;
    const w = document.createTreeWalker(box, NodeFilter.SHOW_TEXT); let out = '';   // the box's words, not the control's
    while (w.nextNode()) if (!el.contains(w.currentNode)) out += ' ' + w.currentNode.textContent;
    return out; };
  const labelFor = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    if (el.getAttribute('aria-labelledby')) {
      const t = el.getAttribute('aria-labelledby').split(/\s+/).map(i => document.getElementById(i)).filter(Boolean)
        .map(n => n.innerText).join(' '); if (clean(t)) return clean(t); }
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    const wrap = el.closest('label'); if (wrap) return clean(own(wrap, el));
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
    const wrap = !l && el.closest('label');
    return /[*✱]\s*$/.test((l ? l.innerText : wrap ? own(wrap, el) : '').trim()); };
  // "#name" when the id is a plain CSS name; Ashby's ids can start with a digit, so those are [id="…"]
  const byId = id => /^[A-Za-z_][\w-]*$/.test(id) ? `#${id}` : `[id="${id}"]`;
  const out = []; const seenGroups = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (!vis(el) && type !== 'file') continue;
    const key = el.id ? byId(el.id) : (el.name ? `[name="${el.name}"]` : null);
    if (!key) continue;
    if (type === 'radio' || type === 'checkbox') {
      const g = el.name || el.id; if (seenGroups.has(g)) continue;
      const group = el.name ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
      seenGroups.add(g);
      const fs = el.closest('fieldset'); const legend = fs && fs.querySelector('legend');
      let label = legend ? clean(legend.innerText) : '';
      const opts = group.map(x => labelFor(x));
      // the first line of the nearest box holding every option, unless that line is an option itself (Ashby's
      // SMS consent: "Yes - I consent…" first, the question "SMS" one box further out). A lone checkbox's own
      // label is its question.
      const isOpt = t => /^(yes|no)\W*$/i.test(t) || (group.length > 1 && opts.some(o => o && (t.startsWith(o) || o.startsWith(t))));
      if (!label) { let p = el.parentElement; for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
        const t = clean((p.innerText || '').split('\n')[0]); if (t && group.every(x => p.contains(x)) && t.length > 2 && !isOpt(t)) { label = t; break; } } }
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
  // Yes/No buttons (Ashby): two buttons that toggle aria-pressed, and often a hidden checkbox holding the answer.
  // Reported as a radio question with the options Yes and No, keyed by the hidden input (or the box's id).
  for (const box of new Set([...document.querySelectorAll('button[aria-pressed]')].map(b => b.parentElement))) {
    const bs = [...box.children].filter(b => b.tagName === 'BUTTON' && b.hasAttribute('aria-pressed'));
    if (bs.length !== 2 || !bs.every(b => /^(yes|no)$/i.test(clean(b.innerText))) || !vis(bs[0])) continue;
    const named = box.querySelector('input[name]');
    const key = named ? `[name="${named.name}"]` : (box.id ? byId(box.id) : null);
    if (!key) continue;
    let head = null;
    for (let p = box.parentElement, i = 0; p && i < 3 && !head; p = p.parentElement, i++) head = p.querySelector('label, legend');
    const pressed = bs.find(b => b.getAttribute('aria-pressed') === 'true');
    out.push({ field: key, label: head ? clean(head.innerText) : labelFor(bs[0]), value: pressed ? clean(pressed.innerText) : '',
               qtype: 'radio', options: bs.map(b => clean(b.innerText)), buttons: true,
               required: !!head && (/required/i.test(head.className) || /\*\s*$/.test(head.innerText.trim())),
               description: '', group: groupFor(box) });
  }
  // custom dropdowns (Workday and others): <button aria-haspopup="listbox">Select One</button>
  for (const el of document.querySelectorAll('button[aria-haspopup="listbox"], [role="button"][aria-haspopup="listbox"]')) {
    if (!vis(el)) continue;
    const auto = el.getAttribute('data-automation-id');
    const key = el.id ? byId(el.id) : (auto ? `[data-automation-id="${auto}"]` : null);
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


async def fill_buttons(page: Page, selector: str, value: str) -> bool:
    """Yes/No buttons beside a hidden input (Ashby): click the one that matches, then check the page took it."""
    box = page.locator(selector).first.locator("xpath=..")
    buttons = box.locator(":scope > button[aria-pressed]")
    idx = _best_option([t.strip() for t in await buttons.all_inner_texts()], value)
    if idx is None:
        return False
    await buttons.nth(idx).click(timeout=5000)
    return await buttons.nth(idx).get_attribute("aria-pressed") == "true"


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


# A text box with its own list of places under it (Lever's Current location): typing shows the list, and leaving the
# box without picking one empties it, so the answer has to be picked.
_IS_LOOKUP_JS = "e => e.classList.contains('location-input') && !!e.parentElement.querySelector('.dropdown-container')"


_COUNTRY_US = {"us", "usa", "united states", "united states of america"}


def _place_parts(text: str) -> list[str]:
    """'Boston, Massachusetts, United States' -> ['boston', 'ma', 'usa']: a US state and the country one way."""
    from ..draft import US_STATES
    names = {v.lower(): k.lower() for k, v in US_STATES.items()}
    out = []
    for p in (x.strip().lower() for x in text.split(",")):
        if p:
            out.append("usa" if p in _COUNTRY_US else names.get(p, p))
    return out


def place_match(texts: list[str], value: str) -> int | None:
    """The one place in `texts` that is `value`: the same city, and every state or country `value` names. 'York, PA'
    is never 'East York, PA, USA', and plain 'Boston' with two Bostons listed is no one's guess: None."""
    want = _place_parts(value)
    if not want:
        return None
    hits = [i for i, t in enumerate(texts)
            if (got := _place_parts(t)) and got[0] == want[0] and all(w in got[1:] for w in want[1:])]
    return hits[0] if len(hits) == 1 else None


async def fill_lookup(page: Page, selector: str, value: str, wait_ms: int = 6000) -> bool:
    """Type the city of `value` into a place lookup, then pick the place that matches `value` ("Boston, MA" picks
    "Boston, MA, USA"). With no matching place, it clears the box and leaves it for you rather than guessing."""
    loc = page.locator(selector).first
    box = loc.locator("xpath=..")
    await loc.scroll_into_view_if_needed(timeout=5000)
    await loc.click(timeout=4000)
    await loc.fill("")
    await page.keyboard.type(value.split(",")[0].strip()[:40], delay=40)
    places = box.locator(".dropdown-location")
    async def leave_empty() -> bool:
        # empty, then leave it: Lever clears the box and its hidden pick (an earlier place) together on leaving
        await loc.fill("")
        await loc.blur()
        return False
    try:
        await places.first.wait_for(state="visible", timeout=wait_ms)
    except PWTimeout:
        return await leave_empty()
    texts = [t.strip() for t in await places.all_inner_texts()]
    idx = place_match(texts, value)
    if idx is None:
        return await leave_empty()
    await places.nth(idx).click(timeout=3000)
    await page.wait_for_timeout(150)
    return (await loc.input_value()).strip() == texts[idx]


async def fill_field(page: Page, selector: str, qtype: str, value: str, file_path: str | None = None) -> bool:
    if qtype == "listbox":
        return await fill_listbox(page, selector, value)
    if qtype == "file":
        if not file_path:
            return False
        await page.locator(selector).first.set_input_files(file_path, timeout=8000)
        return True
    if qtype in ("radio", "multiselect", "checkbox"):
        if await page.locator(selector).first.evaluate(
                "e => !!e.parentElement && !!e.parentElement.querySelector(':scope > button[aria-pressed]')"):
            return await fill_buttons(page, selector, value)
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
    if await loc.evaluate(_IS_LOOKUP_JS):
        return await fill_lookup(page, selector, value)
    return await fill_text(page, selector, value)


SUBMIT_SELECTORS = [
    'button[type="submit"]:has-text("Submit")', 'button:has-text("Submit application")',
    'button:has-text("Submit Application")', 'input[type="submit"]', 'button[type="submit"]',
]
CONFIRM_RE = re.compile(r"thank you for applying|application (has been )?(received|submitted)|"
                        r"application was successfully submitted|"                          # Ashby
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


# Cookie and consent banners. They sit over the form (Lever's covers the bottom of the window), so a real click on
# a field under one lands on the banner. Jobsmith closes them as a careful person would: with a real click on the
# most private choice the banner offers. Reject first, then "essential only", then a plain close (only when the
# banner never speaks of agreeing or accepting, so the close can't be read as a yes). Never Accept, Allow, Agree, OK or Got it: those give away the user's consent, so a banner
# that offers only those stays, and anything it covers is left for the user.
_BANNER_JS = r"""
() => {
  document.querySelectorAll('[data-jobsmith-banner], [data-jobsmith-banner-box]').forEach(e => {
    e.removeAttribute('data-jobsmith-banner'); e.removeAttribute('data-jobsmith-banner-box'); });
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0; };
  const words = e => (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').replace(/\s+/g, ' ').trim();
  const VENDORS = '#onetrust-banner-sdk, #onetrust-pc-sdk, .cc-window, #CybotCookiebotDialog, #truste-consent-track, ' +
    '.osano-cm-dialog, #didomi-notice, .cky-consent-container, #cookie-law-info-bar, #cookiescript_injected, ' +
    '#iubenda-cs-banner, .termly-styles-banner, [data-testid*="cookie" i], [aria-label*="cookie" i], ' +
    '[aria-label*="consent" i], [id*="cookie" i], [class*="cookie-banner" i], [class*="cookie-consent" i], ' +
    '[class*="consent-banner" i], [role="dialog"], [role="alertdialog"], [role="region"]';
  // about cookies, not just "consent": an application's own consent question (to record an interview, to keep your
  // details for later roles) is the user's to answer, whatever it looks like
  const ABOUT = /\bcookies?\b|tracking technolog|store and\/or access information on (a|your) device/i;
  // a container holding the application's own fields is the form, not a banner
  const FORMISH = 'textarea, input[type="file"], input[type="email"], input[type="tel"], input[type="text"], select';
  const fixedish = e => { for (let n = e; n && n !== document.body; n = n.parentElement) {
    const p = getComputedStyle(n).position; if (p === 'fixed' || p === 'sticky') return true; } return false; };
  const found = [...document.querySelectorAll(VENDORS)].filter(e => {
    const t = words(e);
    return vis(e) && t.length < 4000 && ABOUT.test(t) && !e.querySelector(FORMISH) &&
      // a dialog or region is a banner when it floats over the page, or fills a frame of its own (Sourcepoint)
      (e.matches('[role="dialog"], [role="alertdialog"], [role="region"]') ? fixedish(e) || window !== top : true);
  });
  const banners = found.filter(e => !found.some(o => o !== e && o.contains(e)));   // outermost only
  const REJECT = /^(reject|decline|deny|refuse|disagree|opt out)\b(?!.*\baccept)/i;
  const ESSENTIAL = /\b(only|just)\b.*\b(necessary|essential|required|strictly)\b|\b(necessary|essential|required)\b(\s+cookies)?\s+only\b|continue without accepting|use (necessary|essential) cookies only/i;
  const CLOSE = /^(close|dismiss|×|✕|✖|x)$/i;
  const NEVER = /accept|allow|agree|\bok\b|okay|got it|understand|consent to|save|manage|settings|preferences|customi[sz]e|policy|learn more|more info/i;
  for (const b of banners) {
    // A close is pressed only on a plain notice: if the banner's words speak of agreeing or accepting at all ("By
    // closing this you agree", "By clicking X you accept", "Continue browsing to consent"), its close may be a yes
    const prose = (() => {                                            // the banner's words, not its buttons'
      const w = document.createTreeWalker(b, NodeFilter.SHOW_TEXT); let out = '';
      while (w.nextNode()) if (!w.currentNode.parentElement.closest('button, [role="button"], a')) out += ' ' + w.currentNode.textContent;
      return out.replace(/\s+/g, ' '); })();
    const agreesOnClose = /\b(agree|accept|consent|allow|opt(s|ed|ing)?[\s-]*(you\s+)?in\b|(fine|ok|okay|happy) with)/i.test(prose);
    const btns = [...b.querySelectorAll('button, [role="button"], a, input[type="button"], input[type="submit"]')]
      .filter(vis).map(e => ({ e, t: words(e) })).filter(x => x.t && x.t.length < 60);
    const pick = btns.find(x => REJECT.test(x.t)) || btns.find(x => ESSENTIAL.test(x.t)) ||
      (agreesOnClose ? null : btns.find(x => CLOSE.test(x.t) && !NEVER.test(x.t)));
    if (!pick) continue;
    pick.e.setAttribute('data-jobsmith-banner', '1');
    b.setAttribute('data-jobsmith-banner-box', '1');
    return pick.t;
  }
  return null;
}
"""


async def dismiss_banners(page: Page, log=None, rounds: int = 3) -> list[str]:
    """Close cookie/consent banners on the page and its frames with a real click on their most private choice
    (see _BANNER_JS). Returns the words of each button clicked. Safe to call often: with no banner it does nothing.
    A banner that offers only Accept is left alone (the user's consent isn't Jobsmith's to give)."""
    clicked: list[str] = []
    for _ in range(rounds):
        hit = None
        for frame in page.frames:
            try:
                text = await frame.evaluate(_BANNER_JS)
            except Exception:
                continue
            if text:
                hit = (frame, text)
                break
        if not hit:
            break
        frame, text = hit
        btn, box = frame.locator("[data-jobsmith-banner]").first, frame.locator("[data-jobsmith-banner-box]").first
        try:
            await btn.click(timeout=3000)
            await box.wait_for(state="hidden", timeout=3000)
        except Exception:
            if not frame.is_detached():          # a banner in its own frame removes the frame: that's closed
                # it didn't go away: stop trying rather than click around it
                if log:
                    log(f"A cookie banner didn't close when Jobsmith pressed \"{text}\"; fields under it may need you.")
                break
        clicked.append(text)
        if log:
            log(f"Closed a cookie banner with \"{text}\" (the most private choice it offered).")
    return clicked


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
