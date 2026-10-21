import { useContext, useEffect, useState } from "react";
import { api, LiveTab } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, Modal, Steps, useTick } from "../ui";
import { friendly } from "../pages/Tracker";

const WORKING = new Set(["opening", "filling", "submitting"]);
const PHASE: Record<string, string> = { opening: "Opening the form", filling: "Filling in your answers", review: "Ready for you",
  code: "Needs the emailed code", submitting: "Submitting", submitted: "Submitted", error: "Stopped" };

export function CodeBox({ tab, onDone }: { tab: LiveTab; onDone: (m: string) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; message?: string; submitted?: boolean }>(`/api/live/${tab.job_id}/code`, { code });
      onDone(r.ok ? (r.submitted ? "Code entered and submitted." : "Code entered. Click Submit.") : r.message ?? "Couldn't enter it.");
      if (r.ok) setCode("");
    } catch (e) { onDone((e as Error).message); }
    setBusy(false);
  };
  return (
    <div className="codebox">
      <label htmlFor={`code-${tab.job_id}`}>{tab.company} emailed you a code</label>
      <div className="row">
        <input id={`code-${tab.job_id}`} value={code} autoComplete="one-time-code" spellCheck={false}
               onChange={e => setCode(e.target.value)} onKeyDown={e => e.key === "Enter" && code.trim() && send()}
               placeholder="Paste the code" />
        <button className="btn primary" disabled={!code.trim() || busy} onClick={send}>Enter code</button>
      </div>
    </div>
  );
}

function Actions({ tab, onMsg }: { tab: LiveTab; onMsg: (m: string) => void }) {
  const act = async (path: string, ok: string) => {
    try {
      const r = await api.post<{ ok: boolean; message?: string }>(`/api/live/${tab.job_id}/${path}`);
      onMsg(r.ok ? ok : r.message ?? "That didn't work.");
    } catch (e) { onMsg((e as Error).message); }
  };
  return (
    <div className="row tight">
      {tab.phase === "review" && (
        <button className="btn primary sm" onClick={() => confirm(`Submit the ${tab.company} application now?`) && act("submit", "Submit clicked.")}>Submit</button>
      )}
      <button className="btn sm" onClick={() => act("show", "Opening it in a window for you to finish.")} title="Open this application in a browser window and finish it yourself">Take over</button>
      <a className="btn ghost sm" href={`#/job/${tab.job_id}`}>Answers</a>
      <button className="btn ghost sm" onClick={() => act("close", "Tab closed.")} aria-label={`Close the ${tab.company} tab`}><Icon name="x" size={14} /></button>
    </div>
  );
}

export default function Live({ compact = false }: { compact?: boolean }) {
  const { refresh, status } = useContext(StatusCtx);
  const [tabs, setTabs] = useState<LiveTab[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const t = useTick(3000);
  useEffect(() => { api.get<{ tabs: LiveTab[] }>("/api/live").then(r => setTabs(r.tabs)).catch(() => {}); }, [t]);
  if (!tabs.length) return compact ? null : (
    <p className="muted">Nothing in the browser right now.</p>
  );
  const peek = tabs.find(x => x.job_id === open);
  const say = (m: string) => { setMsg(m); refresh(); };

  return (
    <>
      <div className="live-grid">
        {tabs.map(tab => (
          <article key={tab.job_id} className={`live ph-${tab.phase} ${tab.needs_code ? "wants" : ""}`}>
            <a className="shot" href={`#/watch/${tab.job_id}`} aria-label={`Watch ${tab.company} live`}>
              <img src={`/api/live/${tab.job_id}/shot?t=${t}`} alt="" loading="lazy" />
              <span className="watch"><Icon name="eye" size={14} /> Watch live</span>
            </a>
            <div className="live-meta">
              <Logo name={tab.company} size={28} />
              <div>
                <strong>{tab.company}</strong>
                <span className={`phase ph-${tab.phase}`}>{WORKING.has(tab.phase) && <Dots />}{PHASE[tab.phase] ?? tab.phase_label}</span>
              </div>
            </div>
            <Steps p={status?.progress?.[tab.job_id]} />
            {tab.note && tab.phase !== "code" && <p className="muted small clamp1" title={tab.note}>{tab.phase === "error" ? friendly(tab.note) : tab.note}</p>}
            {tab.needs_code && <CodeBox tab={tab} onDone={say} />}
            <Actions tab={tab} onMsg={say} />
          </article>
        ))}
      </div>
      {msg && <p className="toast" role="status">{msg}</p>}
      {peek && (
        <Modal wide onClose={() => setOpen(null)} title={<span className="row tight"><Logo name={peek.company} size={24} />
          <strong>{peek.company}</strong><span className="muted">{peek.title}</span>
          <span className={`phase ph-${peek.phase}`}>{WORKING.has(peek.phase) && <Dots />}{PHASE[peek.phase]}</span></span>}>
          <img className="peek-img" src={`/api/live/${peek.job_id}/shot?t=${t}`} alt={`What the ${peek.company} tab shows right now`} />
          {peek.needs_code && <CodeBox tab={peek} onDone={say} />}
          <Actions tab={peek} onMsg={say} />
        </Modal>
      )}
    </>
  );
}
