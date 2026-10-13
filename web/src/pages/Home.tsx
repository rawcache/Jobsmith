import { useContext, useEffect, useState } from "react";
import { ago, api, OUTCOME_LABEL, tok } from "../api";
import { autopilotOn, setAutopilot, StatusCtx } from "../main";
import { Dots, Icon, Logo } from "../ui";
import Ask from "../components/Ask";
import Live from "../components/Live";
import Setup from "../components/Setup";

type HomeData = {
  applied_today: number; applied_week: number; applied_total: number; in_progress: number; queued: number;
  daily_cap: number; remaining_today: number; autonomy: string; auto_run: boolean; next_run: number | null;
  last_summary: string; min_fit: number; network: number;
  review: { id: string; company: string; title: string; status: string; hold_reason: string | null; error: string | null; updated_at: number }[];
  recent: { id: string; company: string; title: string; outcome: string | null; finished_at: number }[];
  sources: { id: number; url: string; last_synced: number | null; last_count: number | null }[];
};

const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const srcName = (u: string) => u.replace(/^https?:\/\/(www\.)?github\.com\//, "").replace(/\/$/, "");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export default function Home() {
  const { status, refresh } = useContext(StatusCtx);
  const [d, setD] = useState<HomeData | null>(null);
  const [busy, setBusy] = useState("");
  const [newSrc, setNewSrc] = useState("");
  const load = () => api.get<HomeData>("/api/home").then(setD).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const on = autopilotOn(status);
  const runNow = async () => { setBusy("run"); await api.post("/api/auto/run-now").catch(() => {}); setBusy(""); load(); refresh(); };
  const toggle = async () => { await setAutopilot(!on); refresh(); load(); };
  const addSrc = async () => {
    if (!newSrc.trim()) return;
    setBusy("src");
    try { await api.post("/api/sources", { url: newSrc.trim() }); setNewSrc(""); } catch { /* list shows the state */ }
    setBusy(""); load(); refresh();
  };

  return (
    <div className="page home">
      <section className="status-line">
        <h1>{on ? "Autopilot is on." : "Autopilot is off."}</h1>
        {d && (
          <p>
            {on ? <>Sent {plural(d.applied_today, "application")} today, {d.applied_week} this week. {d.queued} good matches are waiting
              {d.next_run ? `, and the next check is at ${clock(d.next_run)}` : ""}. It stops at {d.daily_cap} a day and holds anything it isn't sure about for you.</>
              : <>When it's on, Jobsmith checks your job lists every few hours and applies to roles with a fit of {d.min_fit} or more, under your name, without you at the screen. {d.queued} matches are ready now.</>}
            {status ? <> AI used today: {tok(status.tokens_today)} tokens.</> : null}
          </p>
        )}
        <div className="row tight">
          {on ? (<>
            <button className="btn primary" onClick={runNow} disabled={!!busy}>{busy === "run" ? <Dots /> : "Apply to new matches now"}</button>
            <button className="btn" onClick={toggle}>Pause autopilot</button>
          </>) : <button className="btn primary" onClick={toggle}>Turn on autopilot</button>}
          <a className="link" href="#/stats">Usage and what it learned</a>
        </div>
        {d?.last_summary && <p className="muted small">Last run: {d.last_summary}</p>}
      </section>

      <Ask onDone={load} />
      <Setup />

      {(status?.live ?? 0) > 0 && (
        <section className="card">
          <h2>Applying right now</h2>
          <Live />
        </section>
      )}

      <div className="grid-2">
        <section className="card">
          <h2>Needs you{d && d.review.length ? ` (${d.review.length})` : ""}</h2>
          {!d ? <p className="muted">Loading</p> : d.review.length === 0 ? <p className="muted">Nothing waiting on you.</p> : (
            <ul className="rows">
              {d.review.map(j => (
                <li key={j.id}>
                  <a className="rowlink" href={`#/matches/${j.id}`}>
                    <Logo name={j.company} size={34} />
                    <div className="grow">
                      <strong>{j.company}</strong>, {j.title}
                      <p className="small warn-text">{j.status === "error" ? (j.error ?? "Something went wrong.") : (j.hold_reason ?? "Filled in and ready to submit.")}</p>
                    </div>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Recently applied</h2>
          {d && d.recent.length === 0 ? <p className="muted">Nothing sent yet.</p> : (
            <ul className="rows">
              {d?.recent.map(r => (
                <li key={r.id}>
                  <a className="rowlink" href={`#/matches/${r.id}`}>
                    <Logo name={r.company} size={34} />
                    <div className="grow"><strong>{r.company}</strong>, {r.title}</div>
                    <span className={r.outcome ? "ok-text small" : "muted small"}>{r.outcome ? OUTCOME_LABEL[r.outcome] : ago(r.finished_at)}</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
          <p className="small"><a href="#/tracker">Open the tracker</a></p>
        </section>
      </div>

      <section className="card">
        <h2>Job lists it watches</h2>
        <ul className="rows">
          {d?.sources.map(s => (
            <li key={s.id} className="src">
              <Icon name="github" size={18} />
              <a className="grow" href={s.url} target="_blank" rel="noreferrer">{srcName(s.url)}</a>
              <span className="muted small">{s.last_synced ? `${s.last_count?.toLocaleString()} roles, checked ${ago(s.last_synced)}` : "not checked yet"}</span>
            </li>
          ))}
        </ul>
        <div className="row">
          <input className="grow" value={newSrc} onChange={e => setNewSrc(e.target.value)} onKeyDown={e => e.key === "Enter" && addSrc()}
                 placeholder="Add a GitHub job list, like github.com/SimplifyJobs/New-Grad-Positions" aria-label="GitHub job list URL" />
          <button className="btn" onClick={addSrc} disabled={!newSrc.trim() || !!busy}>{busy === "src" ? <Dots /> : "Add list"}</button>
        </div>
        {d && d.network === 0 && <p className="small muted">To see who you know at each company, import your LinkedIn connections in <a href="#/profile">Profile</a>.</p>}
      </section>
    </div>
  );
}
