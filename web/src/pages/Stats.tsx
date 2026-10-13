import { useEffect, useState } from "react";
import { api, tok, Usage } from "../api";

type Learn = { approved: number; edited: number; rejected: number; rules: string[]; jobs_green: number; jobs_red: number;
  funnel: Record<string, number> };
type U = { today: Usage; all: Usage; avg_per_app: number; apps: number;
  by_purpose: { purpose: string; calls: number; tokens: number; cached: number }[];
  by_model: { backend: string; model: string; calls: number; tokens: number; cost: number | null }[];
  recent: { job_id: string; company: string; title: string; tokens: number; cost: number | null }[] };

const PURPOSE: Record<string, string> = { research: "Company research", answers: "Writing answers", command: "Finding postings",
  profile: "Reading your files", other: "Other" };
const BACKEND: Record<string, string> = { claude_cli: "Claude (subscription)", anthropic_api: "Claude API", openai_api: "OpenAI API" };

export default function Stats() {
  const [l, setL] = useState<Learn | null>(null);
  const [u, setU] = useState<U | null>(null);
  useEffect(() => { api.get<Learn>("/api/learning").then(setL); api.get<U>("/api/usage").then(setU); }, []);
  if (!l || !u) return <div className="page"><p className="muted">Loading…</p></div>;
  const max = Math.max(1, ...u.recent.map(r => r.tokens));

  return (
    <div className="page narrow stats-page">
      <div className="page-h"><div><h1>Usage and learning</h1></div></div>

      <section className="card"><h2>AI usage</h2>
      <table className="kv wide">
        <tbody>
          <tr><th scope="row">Last 24 hours</th><td>{tok(u.today.tokens)} tokens in {u.today.calls} calls{u.today.searches ? `, ${u.today.searches} web searches` : ""}</td></tr>
          <tr><th scope="row">All time</th><td>{tok(u.all.tokens)} tokens in {u.all.calls} calls{u.all.cached ? ` (plus ${tok(u.all.cached)} cached, which costs far less)` : ""}</td></tr>
          <tr><th scope="row">Per application</th><td>{u.apps ? `${tok(u.avg_per_app)} tokens on average across ${u.apps}` : "Nothing yet"}</td></tr>
          {u.all.cost != null && <tr><th scope="row">API-rate value</th><td>~${u.all.cost.toFixed(2)} <span className="muted small">(what Claude Code reports; on a subscription you aren't billed this)</span></td></tr>}
        </tbody>
      </table>
      <p className="muted small">Research is usually the biggest share. It runs once per company and is reused for 14 days. Turning it off in Settings roughly halves usage.</p>

      {u.by_purpose.length > 0 && (<>
        <h3 className="sub">By task</h3>
        <table className="kv wide"><tbody>
          {u.by_purpose.map(p => <tr key={p.purpose}><th scope="row">{PURPOSE[p.purpose] ?? p.purpose}</th>
            <td>{tok(p.tokens)} tokens, {p.calls} calls</td></tr>)}
        </tbody></table>
      </>)}
      {u.by_model.length > 0 && (<>
        <h3 className="sub">By model</h3>
        <table className="kv wide"><tbody>
          {u.by_model.map(m => <tr key={m.backend + m.model}><th scope="row">{BACKEND[m.backend] ?? m.backend} {m.model}</th>
            <td>{tok(m.tokens)} tokens, {m.calls} calls</td></tr>)}
        </tbody></table>
      </>)}
      {u.recent.length > 0 && (<>
        <h3 className="sub">Recent applications</h3>
        <table className="bars"><tbody>
          {u.recent.map(r => (
            <tr key={r.job_id} onClick={() => (location.hash = `#/job/${r.job_id}`)}>
              <th scope="row"><strong>{r.company}</strong> <span className="muted small">{r.title}</span></th>
              <td className="bar"><span style={{ width: `${(r.tokens / max) * 100}%` }} /></td>
              <td className="num">{tok(r.tokens)}</td>
            </tr>))}
        </tbody></table>
      </>)}

      </section><section className="card"><h2>What it learned</h2>
      
      <table className="kv wide"><tbody>
        <tr><th scope="row">{l.approved} approved</th><td>Similar questions build trust toward auto-submit</td></tr>
        <tr><th scope="row">{l.edited} rewritten</th><td>Your rewrites become style examples; short ones get reused directly</td></tr>
        <tr><th scope="row">{l.rejected} rejected</th><td>Your reasons become the rules below</td></tr>
        <tr><th scope="row">{l.jobs_green} / {l.jobs_red} jobs</th><td>Marked good fit / not for me; shifts fit scores for similar jobs</td></tr>
      </tbody></table>
      <h3 className="sub">Rules from your feedback</h3>
      {l.rules.length ? <ul className="rules">{l.rules.map(r => <li key={r}>{r}</li>)}</ul>
        : <p className="muted small">None yet. When you mark an answer "Not right", say what to do differently and it shows up here.</p>}

      </section><section className="card"><h2>After you applied</h2>
      {l.funnel.submitted ? (
        <table className="kv wide"><tbody>
          {[["submitted", "submitted"], ["received", "confirmed received"], ["assessment", "assessments"],
            ["interview", "interviews"], ["offer", "offers"], ["rejected", "rejected"], ["no_reply", "no reply yet"]].map(([k, lab]) =>
            <tr key={k}><th scope="row">{l.funnel[k] ?? 0}</th><td>{lab}</td></tr>)}
        </tbody></table>
      ) : <p className="muted">Nothing submitted yet. Connect Gmail in Settings and replies get tracked (read-only).</p>}
      </section>
    </div>
  );
}
