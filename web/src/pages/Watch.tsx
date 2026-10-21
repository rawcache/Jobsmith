import { useContext, useEffect, useState } from "react";
import { api, LiveTab } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, poll, Steps } from "../ui";
import { CodeBox } from "../components/Live";

/** One application, live: smooth video of the form being filled, and what you can do about it. */
export default function Watch({ id }: { id: string }) {
  const { status, refresh } = useContext(StatusCtx);
  const [tab, setTab] = useState<LiveTab | null | undefined>(undefined);
  const [msg, setMsg] = useState("");
  const [nonce, setNonce] = useState(0);
  const load = () => api.get<{ tabs: LiveTab[] }>("/api/live").then(r => setTab(r.tabs.find(x => x.job_id === id) ?? null)).catch(() => {});
  useEffect(() => { load(); const t = poll(load, 2000); return () => t.stop(); }, [id]);
  const act = async (path: string, ok: string) => {
    try { const r = await api.post<{ ok: boolean; message?: string }>(`/api/live/${id}/${path}`); setMsg(r.ok ? ok : r.message ?? "That didn't work."); }
    catch (e) { setMsg((e as Error).message); }
    refresh();
  };
  const p = status?.progress?.[id];

  return (
    <div className="page watch-page">
      <a className="back" href="#/"><Icon name="back" size={15} />Autopilot</a>
      {tab === undefined ? <p className="muted"><Dots />Connecting</p> : tab === null ? (
        <div className="card"><p>This application isn't open in the browser right now.</p>
          <p className="small muted">It may still be researching and writing answers{p ? ` (${p.label.toLowerCase()})` : ""}. This page picks it up when its form opens.</p>
          <a className="btn sm" href={`#/job/${id}`}>See its answers</a></div>
      ) : (<>
        <header className="watch-h">
          <Logo name={tab.company} size={40} />
          <div className="grow"><h1>{tab.company}</h1><p className="muted">{tab.title}</p></div>
          <div className="row tight">
            {tab.phase === "review" && <button className="btn primary" onClick={() => confirm(`Submit the ${tab.company} application now?`) && act("submit", "Submit clicked.")}>Submit</button>}
            <button className="btn" onClick={() => act("show", "Opening it in a window so you can finish it.")}>Take over</button>
            <a className="btn ghost" href={`#/job/${id}`}>Answers</a>
          </div>
        </header>
        <Steps p={p} />
        {tab.needs_code && <CodeBox tab={tab} onDone={setMsg} />}
        {tab.note && <p className="small muted">{tab.note}</p>}
        <div className="stream">
          <img key={nonce} src={`/api/live/${id}/stream?n=${nonce}`} alt={`The ${tab.company} application, live`} onError={() => setTimeout(() => setNonce(n => n + 1), 2000)} />
        </div>
        {msg && <p className="toast" role="status">{msg}</p>}
      </>)}
    </div>
  );
}
