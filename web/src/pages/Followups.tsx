import { useEffect, useState } from "react";
import { ago, api, OUTCOME_LABEL } from "../api";
import { Dots, Logo } from "../ui";

type Reply = { id: number; kind: string; subject: string; sender: string; received_at: number; job_id: string; company: string; title: string };
type Quiet = { id: string; company: string; title: string; days: number; draft: string };
type Board = { replies: Reply[]; quiet: Quiet[]; waiting: number; email: boolean; counts: Record<string, number> };

/** What companies said back, and the applications that have gone quiet long enough to follow up on. */
export default function Followups() {
  const [b, setB] = useState<Board | null>(null);
  const [copied, setCopied] = useState("");
  const load = () => api.get<Board>("/api/followups").then(setB);
  useEffect(() => { load(); }, []);
  if (!b) return <div className="page"><p className="muted"><Dots />Loading</p></div>;
  const mark = (id: string, action: string) => api.post<Board>(`/api/followups/${id}`, { action }).then(setB);
  const copy = async (id: string, t: string) => { try { await navigator.clipboard.writeText(t); setCopied(id); setTimeout(() => setCopied(""), 1500); } catch { /* by hand */ } };
  return (
    <div className="page">
      <div className="page-h"><div><h1>Inbox and follow-ups</h1>
        <p className="muted">{b.waiting} applications are waiting to hear back. Follow-ups are drafted for you to send.</p></div>
        {!b.email && <a className="btn" href="#/settings/email">Connect email</a>}</div>

      <div className="stages compact">{(["received", "assessment", "interview", "offer", "rejected"] as const).map(k => (
        <span key={k} className={`stage ${b.counts[k] ? "" : "zero"}`}><b>{b.counts[k] ?? 0}</b>{OUTCOME_LABEL[k]}</span>))}</div>

      <section className="card flush">
        <div className="card-h"><h2>Gone quiet</h2><span className="small muted num">{b.quiet.length || ""}</span></div>
        {b.quiet.length === 0 ? <p className="empty">Nothing yet. Applications show up here a week after you apply with no reply.</p> : (
          <ul className="quiet">{b.quiet.map(q => (
            <li key={q.id}>
              <div className="quiet-h"><Logo name={q.company} size={22} /><strong>{q.company}</strong><span className="clamp1">{q.title}</span>
                <span className="muted small mono">{q.days} days</span></div>
              <textarea className="draft-box" defaultValue={q.draft} rows={5} />
              <div className="row tight">
                <button className="btn primary sm" onClick={() => copy(q.id, q.draft)}>{copied === q.id ? "Copied" : "Copy"}</button>
                <button className="btn sm" onClick={() => mark(q.id, "done")}>I followed up</button>
                <button className="btn ghost sm" onClick={() => mark(q.id, "snooze")}>Remind me in a week</button>
              </div>
            </li>))}</ul>)}
      </section>

      <section className="card flush">
        <div className="card-h"><h2>Replies</h2></div>
        {b.replies.length === 0 ? <p className="empty">{b.email ? "No replies found yet." : "Connect your email to see replies here."}</p> : (
          <ul className="lrows">{b.replies.map(r => (
            <li key={r.id}><a href={`#/job/${r.job_id}`}>
              <Logo name={r.company} size={24} />
              <span className="lr-main"><strong>{r.company}</strong><span className="clamp1">{r.subject || r.title}</span></span>
              <span className={`lr-why ${r.kind === "rejected" ? "muted" : "ok-text"}`}>{OUTCOME_LABEL[r.kind] ?? r.kind}</span>
              <span className="lr-when muted">{ago(r.received_at)}</span></a></li>))}</ul>)}
      </section>
    </div>
  );
}
