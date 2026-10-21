import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, Job } from "../api";
import { autopilotOn, setAutopilot, Status, StatusCtx } from "../main";
import { PixelMark } from "../brand";
import { Dots, Icon, Logo, poll, Switch } from "../ui";
import StatusMenu from "./StatusMenu";

/* The frame around every page: a bar across the top (pages, search ⌘K, autopilot, the bell, your account) and a
   centered column of content below it. Rail is kept for narrow embeds and older layouts. */

type NavItem = { key: string; label: string; icon: string; skill?: string };
export const NAV: NavItem[][] = [
  [{ key: "", label: "Home", icon: "home" }, { key: "matches", label: "Matches", icon: "search" },
   { key: "tracker", label: "Applications", icon: "list" }, { key: "companies", label: "Companies", icon: "building" }],
  [{ key: "voice", label: "Your voice", icon: "sparkle", skill: "voice" }, { key: "outreach", label: "Outreach", icon: "users", skill: "outreach" },
   { key: "followups", label: "Follow-ups", icon: "mail", skill: "followups" }],
  [{ key: "documents", label: "Documents", icon: "doc" }, { key: "profile", label: "Profile", icon: "user" },
   { key: "preferences", label: "Job preferences", icon: "sliders" }],
];
const FOOT: NavItem[] = [{ key: "skills", label: "Skills", icon: "grid" }, { key: "activity", label: "Activity", icon: "bolt" },
  { key: "settings", label: "Settings", icon: "gear" }];
export const TITLES: Record<string, string> = Object.fromEntries([...NAV.flat(), ...FOOT].map(n => [n.key, n.label]));
Object.assign(TITLES, { job: "Job", company: "Company", stats: "Usage and learning", watch: "Watch", setup: "Setup" });

const pref = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const keep = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private window */ } };

export function Rail({ cur, status }: { cur: string; status: Status | null }) {
  const [min, setMin] = useState(() => pref("js-rail", "open") === "min");
  useEffect(() => { document.documentElement.dataset.rail = min ? "min" : "open"; keep("js-rail", min ? "min" : "open"); }, [min]);
  const on = (s?: string) => !s || (status?.skills ?? []).some(k => k.key === s && k.enabled);
  const link = (n: NavItem) => (
    <a key={n.key} href={`#/${n.key}`} aria-current={cur === n.key ? "page" : undefined} title={min ? n.label : undefined}>
      <Icon name={n.icon} size={16} /><span className="lbl">{n.label}</span>
      {n.key === "tracker" && status && status.needs_you > 0 && <span className="rail-n">{status.needs_you}</span>}
    </a>);
  return (
    <aside className="rail" aria-label="Main">
      <a href="#/" className="rail-brand" aria-label="Jobsmith home"><PixelMark size={24} /><span className="lbl wordmark">jobsmith</span></a>
      <nav>
        {NAV.map((g, i) => { const items = g.filter(n => on(n.skill)); return items.length ? <div key={i} className="rail-group">{items.map(link)}</div> : null; })}
      </nav>
      <div className="rail-foot">
        {FOOT.map(link)}
        <button className="rail-fold" onClick={() => setMin(v => !v)} aria-label={min ? "Expand the sidebar" : "Collapse the sidebar"}
          title={min ? "Expand" : "Collapse"}>
          <Icon name={min ? "expand" : "collapse"} size={16} /><span className="lbl">Collapse</span></button>
        {status?.version && <span className="lbl ver">v{status.version}</span>}
      </div>
    </aside>
  );
}

const clockAt = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/** What autopilot is doing, in a few words. */
export function apLine(s: Status, on: boolean): string {
  const n = Object.keys(s.active).length;
  if (!on) return "Off";
  if (s.power.paused) return "Paused until you plug in";
  if (s.quota?.limited && !s.quota.fallback) return `Waiting for ${s.quota.name} until ${clockAt(s.quota.resets_at)}`;
  if (n) return `Applying to ${n}`;
  return s.auto.next_run ? `Next check ${clockAt(s.auto.next_run)}` : "On";
}

/** The bar across the top: brand, the pages you use most, everything else under More, then search, autopilot,
    the bell and your account. Content sits in a centered column below it (after Simplify's dashboard). */
const PRIMARY = ["", "matches", "tracker", "companies"];

export function TopBar({ view, status, onToast }: { view: string; status: Status | null; onToast: (m: string) => void }) {
  const { refresh } = useContext(StatusCtx);
  const on = autopilotOn(status);
  const busy = on && status && Object.keys(status.active).length > 0;
  const [more, setMore] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!more) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setMore(false); };
    addEventListener("mousedown", away);
    return () => removeEventListener("mousedown", away);
  }, [more]);
  useEffect(() => { const c = () => setMore(false); addEventListener("hashchange", c); return () => removeEventListener("hashchange", c); }, []);
  const skillOn = (k?: string) => !k || (status?.skills ?? []).some(x => x.key === k && x.enabled);
  const all = [...NAV.flat(), ...FOOT].filter(n => skillOn(n.skill));
  const main = all.filter(n => PRIMARY.includes(n.key));
  const rest = all.filter(n => !PRIMARY.includes(n.key));
  const cur = view === "job" ? "matches" : view === "company" ? "companies" : view;
  const inMore = rest.some(n => n.key === cur);
  return (
    <header className="topnav">
      <div className="topnav-in">
        <a href="#/" className="brand" aria-label="Jobsmith home"><PixelMark size={22} /><span className="wordmark">jobsmith</span></a>
        <nav className="tn-links" aria-label="Main">
          {main.map(n => (
            <a key={n.key} href={`#/${n.key}`} aria-current={cur === n.key ? "page" : undefined}>{n.label}
              {n.key === "tracker" && status && status.needs_you > 0 && <span className="tn-n">{status.needs_you}</span>}</a>))}
          <div className="tn-more" ref={ref}>
            <button aria-expanded={more} aria-current={inMore ? "page" : undefined} onClick={() => setMore(v => !v)}>
              {inMore ? TITLES[cur] : "More"}<Icon name="down" size={12} /></button>
            {more && (
              <div className="tn-pop" role="menu">
                {rest.map(n => (
                  <a key={n.key} role="menuitem" href={`#/${n.key}`} aria-current={cur === n.key ? "page" : undefined}>
                    <Icon name={n.icon} size={15} /><span>{n.label}</span></a>))}
                {status?.version && <span className="tn-ver">Jobsmith v{status.version}</span>}
              </div>)}
          </div>
        </nav>
        <div className="top-r">
          <button className="icon-btn" onClick={() => dispatchEvent(new CustomEvent("js-palette"))}
            title={`Search or jump to (${navigator.platform.includes("Mac") ? "⌘" : "Ctrl"} K)`} aria-label="Search">
            <Icon name="search" size={17} /></button>
          {status && (
            <label className={`forge ${on ? "lit" : ""} ${busy ? "busy" : ""}`} title={on ? "Autopilot applies for you. Turning it off stops everything in progress." : "Turn on to apply automatically"}>
              <span className="forge-dot" aria-hidden />
              <span className="forge-txt"><strong>Autopilot</strong><span className="forge-line">{apLine(status, on)}</span></span>
              <Switch on={on} label="Autopilot" onChange={v => setAutopilot(v).then(m => { onToast(m); refresh(); })} />
            </label>
          )}
          <Bell />
          {status && <StatusMenu s={status} />}
        </div>
      </div>
    </header>
  );
}

type Note = { id: string; kind: string; title: string; detail?: string; job_id?: string; company?: string; at: number; unread: boolean; href?: string; urgent?: boolean };

/** Codes, CAPTCHAs, sign-ins, held applications, replies, and AI trouble: all in one place, out of the way. */
export function Bell() {
  const { refresh } = useContext(StatusCtx);
  const [open, setOpen] = useState(false);
  const [d, setD] = useState<{ items: Note[]; unread: number }>({ items: [], unread: 0 });
  const ref = useRef<HTMLDivElement>(null);
  const load = () => api.get<{ items: Note[]; unread: number }>("/api/notifications").then(setD).catch(() => {});
  useEffect(() => { load(); const t = poll(load, 6000); return () => t.stop(); }, []);
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => api.post("/api/notifications/seen").then(load), 1500);
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    addEventListener("mousedown", away); addEventListener("keydown", esc);
    return () => { clearTimeout(t); removeEventListener("mousedown", away); removeEventListener("keydown", esc); };
  }, [open]);
  useEffect(() => { const c = () => setOpen(false); addEventListener("hashchange", c); return () => removeEventListener("hashchange", c); }, []);
  const urgent = d.items.filter(i => i.urgent).length;
  return (
    <div className="bell" ref={ref}>
      <button className={`icon-btn bell-btn ${urgent ? "hot" : ""}`} aria-label={`Notifications${d.unread ? `, ${d.unread} new` : ""}`}
        aria-expanded={open} onClick={() => setOpen(v => !v)}>
        <Icon name="bell" size={17} />{d.unread > 0 && <span className="bell-n">{d.unread > 9 ? "9+" : d.unread}</span>}
      </button>
      {open && (
        <div className="bell-pop" role="dialog" aria-label="Notifications">
          <div className="bell-h"><strong>Notifications</strong>{urgent > 0 && <span className="small warn-text">{urgent} need you now</span>}</div>
          {d.items.length === 0 ? <p className="empty">Nothing new. Codes, CAPTCHAs and replies show up here.</p> : (
            <ul className="notes">{d.items.map(n => <NoteRow key={n.id} n={n} onDone={() => { load(); refresh(); }} />)}</ul>)}
        </div>
      )}
    </div>
  );
}

function NoteRow({ n, onDone }: { n: Note; onDone: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const icon = { code: "mail", captcha: "alert", signin: "user", held: "list", reply: "mail", quota: "clock", ai: "alert" }[n.kind] ?? "bell";
  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; message?: string; submitted?: boolean }>(`/api/live/${n.job_id}/code`, { code });
      setMsg(r.ok ? (r.submitted ? "Entered and submitted." : "Entered. Click Submit.") : r.message ?? "Couldn't enter it.");
      if (r.ok) { setCode(""); onDone(); }
    } catch (e) { setMsg((e as Error).message); }
    setBusy(false);
  };
  const body = (
    <>
      <span className={`note-ic k-${n.kind}`}>{n.company ? <Logo name={n.company} size={22} /> : <Icon name={icon} size={14} />}</span>
      <span className="grow"><span className="note-t">{n.title}</span>{n.detail && <span className="note-d">{n.detail}</span>}</span>
      {n.unread && !n.urgent && <span className="note-dot" aria-label="new" />}
    </>);
  return (
    <li className={n.urgent ? "urgent" : ""}>
      {n.href ? <a className="note" href={n.href}>{body}</a> : <div className="note">{body}</div>}
      {n.kind === "code" && (
        <div className="note-act">
          <input value={code} onChange={e => setCode(e.target.value)} placeholder="Paste the code" autoComplete="one-time-code" spellCheck={false}
            onKeyDown={e => e.key === "Enter" && code.trim() && send()} aria-label={`Code from ${n.company}`} />
          <button className="btn primary sm" disabled={!code.trim() || busy} onClick={send}>{busy ? <Dots /> : "Enter"}</button>
          <a className="btn ghost sm" href={`#/watch/${n.job_id}`}>Watch</a>
        </div>)}
      {(n.kind === "captcha" || n.kind === "signin") && (
        <div className="note-act"><button className="btn sm" onClick={() => api.post(`/api/live/${n.job_id}/show`).then(onDone)}>Take over</button>
          <a className="btn ghost sm" href={`#/watch/${n.job_id}`}>Watch</a></div>)}
      {msg && <p className="small note-msg">{msg}</p>}
    </li>
  );
}

type Cmd = { id: string; label: string; hint?: string; icon: string; run: () => void };

/** ⌘K: jump to any page or job, or run an action. */
export function Palette() {
  const { status, refresh } = useContext(StatusCtx);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [note, setNote] = useState("");
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(v => !v); }
      else if (e.key === "Escape") setOpen(false);
    };
    const o = () => setOpen(true);
    addEventListener("keydown", k); addEventListener("js-palette", o);
    return () => { removeEventListener("keydown", k); removeEventListener("js-palette", o); };
  }, []);
  useEffect(() => { if (open) { setQ(""); setI(0); setNote(""); } }, [open]);
  useEffect(() => {
    if (q.trim().length < 2) { setJobs([]); return; }
    const t = setTimeout(() => api.get<{ jobs: Job[] }>(`/api/jobs?q=${encodeURIComponent(q.trim())}&limit=6&include_closed=true`).then(r => setJobs(r.jobs)).catch(() => {}), 150);
    return () => clearTimeout(t);
  }, [q]);
  const go = (h: string) => () => { location.hash = h; setOpen(false); };
  const act = (f: () => Promise<string | void>) => () => { f().then(m => { if (m) setNote(m); refresh(); }); };
  const on = autopilotOn(status);
  const all: Cmd[] = useMemo(() => [
    ...[...NAV.flat(), ...FOOT].map(n => ({ id: "p-" + n.key, label: n.label, hint: "Page", icon: n.icon, run: go(`#/${n.key}`) })),
    { id: "a-auto", label: on ? "Turn autopilot off" : "Turn autopilot on", hint: "Action", icon: "bolt", run: act(() => setAutopilot(!on)) },
    { id: "a-run", label: "Look for new roles now", hint: "Action", icon: "search", run: act(() => api.post<{ summary: string }>("/api/auto/run-now").then(r => r.summary)) },
    { id: "a-mail", label: "Check email for replies", hint: "Action", icon: "mail", run: act(() => api.post<{ error?: string; new_outcomes?: number }>("/api/outcomes/check").then(r => r.error ?? `${r.new_outcomes ?? 0} new replies`)) },
    { id: "a-stop", label: "Stop everything", hint: "Action", icon: "x", run: act(() => api.post<{ stopped: number }>("/api/stop", { everything: true }).then(r => `Stopped ${r.stopped}. Autopilot is off.`)) },
    { id: "a-setup", label: "Run setup again", hint: "Action", icon: "sliders", run: () => { api.post("/api/onboarding/restart").then(go("#/setup/1")); } },
    { id: "a-theme", label: "Switch light or dark", hint: "Action", icon: "moon", run: () => { cycleTheme(); setNote(`Theme: ${pref("js-theme", "light")}`); } },
  ], [on]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const list: Cmd[] = [...all.filter(c => words.every(w => c.label.toLowerCase().includes(w))),
    ...jobs.map(j => ({ id: "j-" + j.id, label: `${j.company}: ${j.title}`, hint: j.status === "submitted" ? "Applied" : "Job", icon: "doc", run: go(`#/job/${j.id}`) }))];
  if (!open) return null;
  const pick = list[Math.min(i, list.length - 1)];
  return (
    <div className="scrim top" onClick={() => setOpen(false)}>
      <div className="palette" role="dialog" aria-label="Search or run a command" onClick={e => e.stopPropagation()}>
        <div className="pal-in"><Icon name="search" size={16} />
          <input autoFocus value={q} placeholder="Search pages, jobs and actions" onChange={e => { setQ(e.target.value); setI(0); }}
            onKeyDown={e => {
              if (e.key === "ArrowDown") { e.preventDefault(); setI(v => Math.min(v + 1, list.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setI(v => Math.max(v - 1, 0)); }
              else if (e.key === "Enter" && pick) pick.run();
            }} /></div>
        {note && <p className="pal-note">{note}</p>}
        <ul className="pal-list">{list.slice(0, 14).map((c, n) => (
          <li key={c.id}><button className={n === i ? "on" : ""} onMouseEnter={() => setI(n)} onClick={c.run}>
            {c.id.startsWith("j-") ? <Logo name={c.label.split(":")[0]} size={18} /> : <Icon name={c.icon} size={15} />}
            <span className="grow clamp1">{c.label}</span><span className="pal-hint">{c.hint}</span></button></li>))}
          {list.length === 0 && <li className="empty">Nothing matches.</li>}</ul>
      </div>
    </div>
  );
}

// Light by default (cool white and cobalt). Dark, or following the computer, is your choice in the account menu.
export function applyTheme() {
  const t = pref("js-theme", "light");
  document.documentElement.dataset.theme = t;
}
export function cycleTheme() {
  const next = { light: "dark", dark: "system", system: "light" }[pref("js-theme", "light")] ?? "light";
  keep("js-theme", next); applyTheme();
  return next;
}
export const themeName = () => pref("js-theme", "light");
