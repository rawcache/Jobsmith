import { useContext, useEffect, useState } from "react";
import { ago, api, companyHref, Draft, Job, LiveTab, Match, OUTCOME_LABEL, Person, Run, tok, Usage } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, MatchText, Modal, useTick } from "../ui";
import ConnectClaude from "../components/ConnectClaude";

type Section = { heading: string; kind: string; items: string[] };
type Resp = { job: Job; drafts: Draft[]; runs: Run[]; readiness: { ready: boolean; blockers: string[] } | null;
  busy?: string; can_fill: boolean; usage: Usage; match: Match; connections: Person[]; sections: Section[] };

const SOURCE: Record<string, string> = {
  answer_bank: "from your profile", learned: "reused from an answer you approved", generated: "written by AI", file: "file",
};

function state(d: Draft): string {
  if (d.verdict === "red") return "red";
  if (d.required && !(d.final_answer ?? d.answer) && d.qtype !== "file") return "amber";
  if (d.verdict === "green" || d.final_answer) return "green";
  if (d.issues.length) return "amber";
  return "blue";
}

function AnswerRow({ d, onChange }: { d: Draft; onChange: () => void }) {
  const value = d.final_answer ?? d.answer;
  const [text, setText] = useState(value);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState(d.note ?? "");
  useEffect(() => setText(d.final_answer ?? d.answer), [d.final_answer, d.answer]);
  const dirty = text !== value;
  const save = (body: object) => api.put(`/api/drafts/${d.id}`, body).then(onChange);
  const isLong = d.qtype === "textarea" || value.length > 90;
  const src = d.kind === "learned" ? d.rationale : d.kind === "generated" && d.model ? `written by ${d.model}` : SOURCE[d.kind] ?? d.kind;

  return (
    <li className={`ans st-${state(d)}`}>
      <label htmlFor={`a-${d.id}`} className="ans-q">{d.label}{d.required ? <span className="req"> (required)</span> : null}</label>
      {d.qtype === "file" && d.kind !== "generated" ? (
        <p>Your resume PDF is attached.</p>
      ) : (d.qtype === "select" || d.qtype === "radio") && d.options.length ? (
        <select id={`a-${d.id}`} value={text} onChange={e => { setText(e.target.value); save({ final_answer: e.target.value }); }}>
          <option value="">Leave blank</option>
          {d.options.map(o => <option key={o}>{o}</option>)}
        </select>
      ) : isLong ? (
        <textarea id={`a-${d.id}`} value={text} rows={Math.min(14, Math.max(3, Math.ceil(text.length / 85)))} onChange={e => setText(e.target.value)} />
      ) : (
        <input id={`a-${d.id}`} value={text} onChange={e => setText(e.target.value)} />
      )}
      <p className="ans-meta">
        <span>{src[0].toUpperCase() + src.slice(1)}.</span>
        {d.facts.length > 0 && <> Based on {[...new Set(d.facts.map(f => (f.subject || f.category).split(" | ")[0]))].map((k, i, a) => (
          <span key={k} className="cite" title={d.facts.filter(f => (f.subject || f.category).startsWith(k)).map(f => f.text).join("\n\n")}>
            {k}{i < a.length - 1 ? ", " : ""}</span>))}.</>}
      </p>
      {d.issues.length > 0 && <p className="issue">{d.issues.join(" ")}</p>}
      {d.note && d.verdict === "red" && <p className="ans-meta">Your note: {d.note}</p>}
      <div className="ans-act">
        {dirty && <button className="btn primary sm" onClick={() => save({ final_answer: text, verdict: "green" })}>Save edit</button>}
        {!dirty && d.verdict !== "green" && (value.trim() || d.qtype === "file") && <button className="link" onClick={() => save({ verdict: "green" })}>Looks right</button>}
        {!dirty && d.verdict !== "red" && <button className="link" onClick={() => setRejecting(r => !r)}>Not right</button>}
        {(d.verdict || d.final_answer) && <button className="link" onClick={() => save({ clear_verdict: true, final_answer: d.answer })}>Undo</button>}
        {d.verdict === "green" && !dirty && <span className="ok-text">Approved</span>}
      </div>
      {rejecting && (
        <div className="row">
          <input className="grow" autoFocus placeholder="What should it do differently next time?" value={note} onChange={e => setNote(e.target.value)} />
          <button className="btn sm" onClick={() => { save({ verdict: "red", note }); setRejecting(false); }}>Save</button>
        </div>
      )}
    </li>
  );
}

function ProfileAnswers({ rows, onChange, approveAll }: { rows: Draft[]; onChange: () => void; approveAll?: () => void }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="sub-h"><span />
        {approveAll && <button className="link" onClick={approveAll}>Approve all</button>}</div>
      <table className="kv">
        <tbody>
          {rows.map(d => (open === d.id ? (
            <tr key={d.id}><td colSpan={2}><ul className="answers"><AnswerRow d={d} onChange={() => { setOpen(null); onChange(); }} /></ul></td></tr>
          ) : (
            <tr key={d.id} className="clicky" onClick={() => setOpen(d.id)} tabIndex={0} onKeyDown={e => e.key === "Enter" && setOpen(d.id)}>
              <th scope="row">{d.label}</th>
              <td>{d.qtype === "file" ? "Resume PDF" : (d.final_answer ?? d.answer) || <span className="muted">Left blank</span>}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </>
  );
}

function Referral({ job, onSaved }: { job: Job; onSaved: () => void }) {
  const [name, setName] = useState(job.referral_name ?? "");
  const [url, setUrl] = useState(job.referral_url ?? "");
  return (
    <div className="referral">
      <div className="grid-2 tight">
        <label className="field">Referred by<input value={name} onChange={e => setName(e.target.value)} placeholder="Full name" /></label>
        <label className="field">Referral link<input value={url} onChange={e => setUrl(e.target.value)} placeholder="Optional" /></label>
      </div>
      <div className="row tight">
        <button className="btn sm" onClick={() => api.post(`/api/jobs/${job.id}/referral`, { name, url }).then(onSaved)}>Save referral</button>
        {job.referral_name && <button className="link" onClick={() => api.post(`/api/jobs/${job.id}/referral`, {}).then(onSaved)}>Remove</button>}
      </div>
    </div>
  );
}

function LivePeek({ id, company }: { id: string; company: string }) {
  const t = useTick(1500);
  const [tab, setTab] = useState<LiveTab | null>(null);
  const [big, setBig] = useState(false);
  useEffect(() => { api.get<{ tabs: LiveTab[] }>("/api/live").then(r => setTab(r.tabs.find(x => x.job_id === id) ?? null)).catch(() => {}); }, [t]);
  if (!tab) return null;
  return (
    <section className="block">
      <h3>In the browser now <span className="muted">{tab.phase_label}</span></h3>
      <button className="shot" onClick={() => setBig(true)} aria-label="Watch larger"><img src={`/api/live/${id}/shot?t=${t}`} alt="" /></button>
      <div className="row tight">
        {tab.phase === "review" && <button className="btn primary sm" onClick={() => confirm(`Submit the ${company} application now?`) && api.post(`/api/live/${id}/submit`)}>Submit</button>}
        <button className="btn sm" onClick={() => api.post(`/api/live/${id}/show`)}>Take over</button>
      </div>
      {big && <Modal wide title={<strong>{company}</strong>} onClose={() => setBig(false)}><img className="peek-img" src={`/api/live/${id}/shot?t=${t}`} alt="" /></Modal>}
    </section>
  );
}

const SECTION_ORDER = ["requirements", "responsibilities", "preferred", "pay", "benefits"];
const SECTION_TITLE: Record<string, string> = { requirements: "Requirements", responsibilities: "Responsibilities",
  preferred: "Desired qualifications", pay: "Pay", benefits: "Benefits" };

/** One job. `embedded` is the right-hand pane on Matches; otherwise it's a full page. */
export default function JobPage({ id, embedded = false }: { id: string; embedded?: boolean }) {
  const { refresh, status } = useContext(StatusCtx);
  const [r, setR] = useState<Resp | null>(null);
  const [err, setErr] = useState("");
  const [fullPosting, setFullPosting] = useState(false);
  const load = () => api.get<Resp>(`/api/jobs/${id}`).then(x => { setR(x); setErr(""); }).catch(e => setErr(e.message));
  useEffect(() => { setR(null); setFullPosting(false); load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [id]);
  if (err) return <div className="jobview"><p>{err}</p></div>;
  if (!r) return <div className="jobview"><p className="muted"><Dots />Loading</p></div>;

  const { job, drafts, runs, readiness, usage, match, connections, sections } = r;
  const res = job.research ?? {};
  const act = async (path: string, body?: object) => { await api.post(`/api/jobs/${id}/${path}`, body); refresh(); load(); };
  const autopilot = () => api.post("/api/jobs/batch", { action: "autopilot", ids: [id] }).then(() => { refresh(); load(); });
  const needs = drafts.filter(d => ["amber", "red"].includes(state(d)));
  const written = drafts.filter(d => !needs.includes(d) && (d.kind === "generated" || d.kind === "learned"));
  const fromProfile = drafts.filter(d => !needs.includes(d) && !written.includes(d));
  const unapproved = fromProfile.filter(d => !d.verdict && !d.final_answer).length;
  const lastShot = runs.find(x => x.screenshot);
  const applied = job.status === "submitted";
  const byKind = Object.fromEntries(sections.map(s => [s.kind, s]));
  const people = res.people ?? [];

  return (
    <div className={`jobview ${embedded ? "embedded" : "page narrow"}`}>
      {!embedded && <a className="back" href="#/matches"><Icon name="back" size={15} />Matches</a>}

      <header className="jv-head">
        <Logo name={job.company} size={52} />
        <div className="grow">
          <a className="co" href={companyHref(job.company)}>{job.company}</a>
          {res.what_the_team_builds && <p className="muted tagline">{res.what_the_team_builds}</p>}
        </div>
        {embedded && <a className="link small" href={`#/job/${id}`}>Open full page</a>}
      </header>
      <h1 className="jv-title">{job.title}</h1>
      <ul className="facts">
        {job.terms.length > 0 && <li>{job.terms.join(", ")}</li>}
        {job.locations.length > 0 && <li>{job.locations.slice(0, 3).join("; ")}{job.locations.length > 3 ? ` and ${job.locations.length - 3} more` : ""}</li>}
        {job.date_posted && <li>Posted {ago(job.date_posted)}</li>}
        {job.sponsorship && <li>{job.sponsorship}</li>}
        <li>Applies through {job.ats}. <a href={job.url} target="_blank" rel="noreferrer">See the posting</a></li>
      </ul>

      <div className="apply-bar">
        {applied ? <p className="ok-text strong"><Icon name="check" size={16} /> Applied{job.outcome ? `. ${OUTCOME_LABEL[job.outcome]}.` : ""}</p>
          : r.busy ? <p className="strong accent-text"><Dots />{r.busy === "drafting" ? "Researching and drafting answers" : "Autopilot is applying"}</p>
          : (<>
            <button className="btn primary" onClick={autopilot}>Apply with autopilot</button>
            {drafts.length > 0 && r.can_fill && <button className="btn" onClick={() => act("fill", { submit: false })}>Fill it, I'll submit</button>}
            {(job.status === "filled" || !r.can_fill) && <button className="link" onClick={() => act("submitted")}>I submitted it myself</button>}
          </>)}
      </div>
      {status && !status.llm.ok && <div className="note warn"><p>No AI is connected, so only answers from your profile get filled.</p><ConnectClaude compact /></div>}
      {job.hold_reason && job.status === "filled" && <p className="note warn">Autopilot held this for you: {job.hold_reason}</p>}
      {job.error && !/connect/i.test(job.error) && <p className="note warn">{job.error}</p>}

      <LivePeek id={id} company={job.company} />

      <section className="block">
        <h3>About the job</h3>
        {res.summary && <p>{res.summary}</p>}
        {SECTION_ORDER.filter(k => byKind[k]).map(k => (
          <div key={k}><h4>{SECTION_TITLE[k]}</h4><ul>{byKind[k].items.map((t, i) => <li key={i}>{t}</li>)}</ul></div>
        ))}
        {!res.summary && sections.length === 0 && !job.description && <p className="muted">Jobsmith reads the posting when it drafts or applies.</p>}
        {job.description && (<>
          <button className="link" onClick={() => setFullPosting(v => !v)}>{fullPosting ? "Hide the full posting" : "Read the full posting"}</button>
          {fullPosting && <pre className="posting">{job.description}</pre>}
        </>)}
      </section>

      <section className="block">
        <h3>How your resume matches</h3>
        {match.score == null ? <p className="muted">No posting text yet.</p> : (<>
          <p><MatchText score={match.score} matched={match.matched.length} total={match.total} /> this posting asks for show up on your resume.</p>
          {match.matched.length > 0 && <p><span className="muted">On your resume:</span> {match.matched.join(", ")}.</p>}
          {match.missing.length > 0 && <p><span className="muted">Not on it:</span> {match.missing.join(", ")}.</p>}
        </>)}
        {res.fit_angles && res.fit_angles.length > 0 && (<><h4>Where you fit</h4><ul>{res.fit_angles.map(a => <li key={a.angle}>{a.angle}</li>)}</ul></>)}
      </section>

      <section className="block">
        <h3>Get referred</h3>
        {connections.length === 0 && people.length === 0 && (
          <p className="muted">Nobody yet. <a href="#/profile">Import your LinkedIn connections</a> to see who you know at {job.company}.</p>
        )}
        {connections.length > 0 && (<>
          <h4>People you know at {job.company}</h4>
          <ul className="people">{connections.map(p => (
            <li key={p.url || p.first_name + p.last_name}><a href={p.url} target="_blank" rel="noreferrer">{p.first_name} {p.last_name}</a>
              <span className="muted">, {p.position}</span></li>))}</ul>
        </>)}
        {people.length > 0 && (<>
          <h4>Hiring managers and alumni</h4>
          <ul className="people">{people.map(p => (
            <li key={p.name}>{p.source_url ? <a href={p.source_url} target="_blank" rel="noreferrer">{p.name}</a> : <strong>{p.name}</strong>}
              <span className="muted">, {p.role}{p.why_relevant ? `. ${p.why_relevant}` : ""}</span></li>))}</ul>
        </>)}
        <details><summary>{job.referral_name ? `Referred by ${job.referral_name}` : "Someone referred you?"}</summary><Referral job={job} onSaved={load} /></details>
      </section>

      <section className="block">
        <div className="sub-h"><h3>Your answers{drafts.length ? ` (${drafts.length})` : ""}</h3>
          {drafts.length > 0 && !r.busy && <button className="link" onClick={() => act("prepare")}>Redraft</button>}</div>
        {drafts.length === 0 ? (
          <p className="muted">None yet. Applying drafts every answer first. <button className="link" onClick={() => act("prepare")} disabled={!!r.busy}>Draft without applying</button></p>
        ) : (<>
          {readiness && !readiness.ready && !applied && (
            <p className="muted">Autopilot would stop on {readiness.blockers.length} of these: {readiness.blockers.slice(0, 3).join("; ")}{readiness.blockers.length > 3 ? "; and more" : ""}.</p>)}
          {needs.length > 0 && (<details open={needs.length <= 6}><summary>Needs you ({needs.length})</summary>
            <ul className="answers">{needs.map(d => <AnswerRow key={d.id} d={d} onChange={load} />)}</ul></details>)}
          {written.length > 0 && (<details open={!embedded}><summary>Written for this job ({written.length})</summary>
            <ul className="answers">{written.map(d => <AnswerRow key={d.id} d={d} onChange={load} />)}</ul></details>)}
          {fromProfile.length > 0 && (<details><summary>From your profile ({fromProfile.length})</summary>
            <ProfileAnswers rows={fromProfile} onChange={load} approveAll={unapproved ? () => act("approve-standard") : undefined} /></details>)}
        </>)}
      </section>

      <section className="block">
        <h3>About {job.company}</h3>
        {res.summary ? <p>{res.values_and_culture || res.what_the_team_builds || "Researched when Jobsmith applies."}</p> : <p className="muted">Researched the first time Jobsmith applies here.</p>}
        {res.tech_stack && res.tech_stack.length > 0 && <p><span className="muted">Stack:</span> {res.tech_stack.join(", ")}.</p>}
        {res.red_flags && res.red_flags.length > 0 && <p><span className="muted">Worth knowing:</span> {res.red_flags.join(" ")}</p>}
        <p><a href={companyHref(job.company)}>Everything at {job.company}</a></p>
        <details><summary>Your call on this job{job.verdict ? `: ${job.verdict === "green" ? "good fit" : "not for me"}` : ""}</summary>
          <div className="row tight">
            <button className={`btn sm ${job.verdict === "green" ? "on" : ""}`} onClick={() => act("verdict", { verdict: "green" })}>Good fit</button>
            <button className={`btn sm ${job.verdict === "red" ? "on" : ""}`} onClick={() => act("verdict", { verdict: "red" })}>Not for me</button>
          </div>
        </details>
      </section>

      {runs.length > 0 && (
        <section className="block">
          <details><summary>Activity{usage.tokens ? `, ${tok(usage.tokens)} AI tokens` : ""}</summary>
            {runs.slice(0, 5).map(x => (
              <div key={x.id} className="run">
                <p><strong>{x.kind === "fill" ? "Filled the form" : x.kind === "draft" ? "Researched and drafted" : x.kind === "submit" ? "Submitted" : x.kind}</strong>
                  <span className="muted"> {new Date(x.started_at * 1000).toLocaleString()}</span></p>
                <pre className="log">{x.log}</pre>
              </div>))}
            {lastShot && <p><a href={`/api/runs/${lastShot.id}/screenshot`} target="_blank" rel="noreferrer">Screenshot of the filled form</a></p>}
          </details>
        </section>
      )}
    </div>
  );
}
