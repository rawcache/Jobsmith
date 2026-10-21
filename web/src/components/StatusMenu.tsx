import { useContext, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Status, StatusCtx } from "../main";
import { Dots, Icon } from "../ui";
import { cycleTheme, themeName } from "./Shell";

const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export const initials = (s: Status | null) => {
  const f = s?.me?.first_name?.trim() ?? "", l = s?.me?.last_name?.trim() ?? "";
  return ((f[0] ?? "") + (l[0] ?? "")).toUpperCase() || "J";
};

/** Something worth a dot: the AI can't write or its free limit ran out. */
export function health(s: Status): "ok" | "warn" {
  return !s.llm.writing.ok || s.quota?.limited ? "warn" : "ok";
}

/** Bottom of the sidebar: your initials and name. Opens upward with everything about the machine side
 *  of Jobsmith (AI and its free limit, this computer, email), settings, and Stop everything. */
export default function StatusMenu({ s }: { s: Status }) {
  const { refresh } = useContext(StatusCtx);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(themeName());
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    addEventListener("mousedown", away); addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", away); removeEventListener("keydown", esc); };
  }, [open]);
  useEffect(() => { const close = () => setOpen(false); addEventListener("hashchange", close); return () => removeEventListener("hashchange", close); }, []);

  const h = health(s);
  const q = s.quota;
  const w = s.llm.writing;
  const n = Object.keys(s.active).length;
  const b = s.power.battery;
  const name = [s.me?.first_name, s.me?.last_name].filter(Boolean).join(" ") || "You";
  const recheck = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.post<{ ok: boolean; message: string }>("/api/quota/recheck"); setMsg(r.message); }
    catch (e) { setMsg((e as Error).message); }
    setBusy(false); refresh();
  };
  const stop = async () => {
    const r = await api.post<{ stopped: number }>("/api/stop", { everything: true });
    setMsg(`Stopped ${r.stopped} application${r.stopped === 1 ? "" : "s"}. Autopilot is off.`); refresh();
  };

  return (
    <div className="smenu" ref={ref}>
      <button className="acct" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(v => !v)} aria-label={`${name}: account and status`}>
        <span className={`avatar ${h === "warn" ? "dot-warn" : ""}`} aria-hidden>{initials(s)}</span>
      </button>
      {open && (
        <div className="smenu-pop" role="menu">
          <div className="smenu-me"><strong>{name}</strong><a className="small" href="#/profile">Profile</a></div>
          <div className="smenu-sec">
            <div className="smenu-row"><span className={`sdot ${w.ok && !q?.limited ? "ok" : "warn"}`} />
              <div className="grow">
                <strong>{w.ok ? w.label.replace(/ \((.*)\)/, "") : "AI not connected"}</strong>
                {q && (w.ok || q.limited) ? (q.limited
                  ? <p className="small muted">Free daily limit used. Back at {clock(q.resets_at)}{q.fallback ? "; smith writes until then." : "."}</p>
                  : <><p className="small muted">{q.used}{q.limit ? ` of ~${q.limit}` : ""} free requests today, resets {clock(q.resets_at)}</p>
                    {q.limit ? <span className="q-bar wide"><span style={{ width: `${Math.min(100, q.used / q.limit * 100)}%` }} /></span> : null}</>)
                  : !w.ok && <p className="small muted">{w.message}</p>}
              </div>
            </div>
            {(q?.limited || !w.ok) && <div className="smenu-act">
              {q?.limited && <button className="btn sm" onClick={recheck} disabled={busy}>{busy ? <Dots /> : "Check again"}</button>}
              <a className="btn sm ghost" href="#/settings">AI settings</a></div>}
          </div>
          <div className="smenu-sec">
            <a className="smenu-row link-row" href="#/activity"><span className={`sdot ${s.power.saver || s.power.paused ? "warn" : "ok"}`} />
              <div className="grow"><strong>{s.power.paused ? "Paused on battery" : n ? `${n} running` : "Idle"}</strong>
                <p className="small muted">{s.power.saver ? "Battery saver on" : "Normal speed"}{b ? `, battery ${b.percent}%` : ""}</p></div></a>
            <a className="smenu-row link-row" href="#/settings/email"><span className={`sdot ${s.email?.ready ? "ok" : "off"}`} />
              <div className="grow"><strong>{s.email?.ready ? "Email connected" : "Connect your email"}</strong>
                <p className="small muted">{s.email?.ready ? s.email.address : "For emailed codes and replies"}</p></div></a>
          </div>
          <div className="smenu-sec smenu-links">
            <button onClick={() => setTheme(cycleTheme())}><Icon name="moon" size={15} />Theme: {theme === "system" ? "match my computer" : theme}</button>
            <a href="#/stats"><Icon name="clock" size={15} />Usage and learning</a>
            <button className="danger-link" onClick={stop}><Icon name="x" size={15} />Stop everything</button>
          </div>
          {msg && <p className="small smenu-msg">{msg}</p>}
        </div>
      )}
    </div>
  );
}
