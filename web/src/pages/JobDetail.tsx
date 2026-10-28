import { useContext, useEffect, useState } from "react";
import { ago, api, companyHref, Draft, FitGate, Job, LiveTab, Match, OUTCOME_LABEL, Person, Run, tok, Usage } from "../api";
import { friendly } from "./Tracker";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, MatchText, Modal, useTick, poll } from "../ui";
import AuditTrail, { Field, FieldsTable } from "../components/AuditTrail";

type Section = { heading: string; kind: string; items: string[] };
type Resp = { job: Job; drafts: Draft[]; runs: Run[]; readiness: { ready: boolean; blockers: string[] } | null;
  busy?: string; can_fill: boolean; usage: Usage; match: Match; connections: Person[]; sections: Section[];
  eligibility: { ok: boolean; reasons: string[]; notes: string[] };
  ai_policy: string | null; trap: string | null; gate: FitGate; approval: Approval | null;
  posting_marked: { text: string; trap: { how: string; attention: boolean } | null }[] | null;
  facts: { pay: string; level: string; mode: string; category: string; sponsorship: string; degree: string } };

// Autopilot's first submission (on this site), filled and waiting for you to approve it.
type Approval = { site: string; site_name: string; asked_at: number;
  answers: { filled_at: number; fields: Field[]; untraced: number } | null };

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

function LivePeek({ id, company, approve }: { id: string; company: string; approve?: boolean }) {
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
        {tab.phase === "review" && !approve && <button className="btn primary sm" onClick={() => confirm(`Submit the ${company} application now?`) && api.post(`/api/live/${id}/submit`)}>Submit</button>}
        <button className="btn sm" onClick={() => api.post(`/api/live/${id}/show`)}>Take over</button>
      </div>
      {big && <Modal wide title={<strong>{company}</strong>} onClose={() => setBig(false)}><img className="peek-img" src={`/api/live/${id}/shot?t=${t}`} alt="" /></Modal>}
    </section>
  );
}

/** Autopilot's first submission, or its first on this site: every answer it filled in and where each came from.
 *  Nothing is sent until you approve; after that, autopilot submits on this site on its own within your limits. */
function FirstRun({ id, company, a, hold, onDone }: { id: string; company: string; a: Approval; hold?: string | null; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const fields = a.answers?.fields ?? [];
  const approve = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; message: string }>(`/api/jobs/${id}/approve`);
      setMsg(r.message);
      if (r.ok) onDone();
    } catch (e) { setMsg((e as Error).message); }
    setBusy(false);
  };
  return (
    <section className="note first-run">
      <h3>Approve autopilot's first submission{a.site_name ? ` on ${a.site_name}` : ""}</h3>
      <p className="small">{hold ?? `Check every answer for ${company}, then approve it to send it.`}</p>
      {fields.length > 0 ? <FieldsTable fields={fields} />
        : <p className="small muted">No answers were recorded for this form. Take over to look at it before you approve.</p>}
      {a.answers && a.answers.untraced > 0 && <p className="small bad-text">{a.answers.untraced} answer{a.answers.untraced > 1 ? "s don't" : " doesn't"} trace to your resume or profile. Check {a.answers.untraced > 1 ? "them" : "it"} before you approve.</p>}
      <div className="row tight">
        <button className="btn primary sm" disabled={busy} onClick={approve}>{busy ? "Sending" : "Approve and send"}</button>
        <button className="btn sm" onClick={() => api.post(`/api/live/${id}/show`)}>Take over</button>
      </div>
      {msg && <p className="small" role="status">{msg}</p>}
    </section>
  );
}

/** The cover letter, as employers will get it: read it, edit it, open the PDF that gets attached. */
function CoverLetter({ id, d, busy, onChange }: { id: string; d?: Draft; busy: boolean; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [writing, setWriting] = useState(false);
  const [err, setErr] = useState("");
  const value = d ? (d.final_answer ?? d.answer) : "";
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const write = async () => {
    setWriting(true); setErr("");
    try { await api.post(`/api/jobs/${id}/cover-letter`); onChange(); } catch (e) { setErr((e as Error).message); }
    setWriting(false);
  };
  const save = () => api.put(`/api/drafts/${d!.id}`, { final_answer: text, verdict: "green" }).then(() => { setEditing(false); onChange(); });
  return (
    <section className="block cover">
      <div className="sub-h"><h3>Cover letter</h3>
        {value && <a className="link" href={`/api/jobs/${id}/cover-letter.pdf?v=${encodeURIComponent(value.length + (d?.verdict ?? ""))}`} target="_blank" rel="noreferrer">Open the PDF that gets attached</a>}</div>
      {!value ? (
        <p className="muted">{d ? "Not written yet: connect an AI in Settings, then Redraft." : "This application doesn't ask for one."}{" "}
          {!d && <button className="link" onClick={write} disabled={writing || busy}>{writing ? <><Dots />Writing</> : "Write one anyway"}</button>}</p>
      ) : editing ? (<>
        <textarea className="letter-edit" value={text} rows={Math.min(22, Math.max(8, Math.ceil(text.length / 80)))} onChange={e => setText(e.target.value)} />
        <div className="row tight"><button className="btn primary sm" onClick={save}>Save</button><button className="link" onClick={() => { setText(value); setEditing(false); }}>Cancel</button></div>
      </>) : (<>
        <div className="letter">{value.split(/\n+/).map((p, i) => <p key={i}>{p}</p>)}</div>
        <div className="row tight">
          <button className="btn sm" onClick={() => setEditing(true)}>Edit</button>
          {d && d.verdict !== "green" && <button className="link" onClick={() => api.put(`/api/drafts/${d.id}`, { verdict: "green" }).then(onChange)}>Looks right</button>}
          {d?.verdict === "green" && <span className="ok-text small">Approved</span>}
        </div>
      </>)}
      {err && <p className="warn-text small">{err}</p>}
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
  const [tab, setTab] = useState<"overview" | "company" | "application">("overview");
  const load = () => api.get<Resp>(`/api/jobs/${id}`).then(x => { setR(x); setErr(""); }).catch(e => setErr(e.message));
  useEffect(() => { setR(null); setFullPosting(false); setTab("overview"); load(); const t = poll(load, 3000); return () => t.stop(); }, [id]);
  if (err) return <div className="jobview"><p>{err}</p></div>;
  if (!r) return <div className="jobview"><p className="muted"><Dots />Loading</p></div>;

  const { job, drafts, runs, readiness, usage, match, connections, sections, eligibility, ai_policy, trap, gate, posting_marked, approval } = r;
  const showTrap = () => { setTab("overview"); setFullPosting(true); };
  const unsure = eligibility && !eligibility.ok;
  const res = job.research ?? {};
  const act = async (path: string, body?: object) => { await api.post(`/api/jobs/${id}/${path}`, body); refresh(); load(); };
  const autopilot = () => api.post("/api/jobs/batch", { action: "autopilot", ids: [id] }).then(() => { refresh(); load(); });
  const isCover = (d: Draft) => /cover/i.test(d.field + " " + d.label);
  const cover = drafts.find(isCover);
  const needs = drafts.filter(d => !isCover(d) && ["amber", "red"].includes(state(d)));
  const written = drafts.filter(d => !isCover(d) && !needs.includes(d) && (d.kind === "generated" || d.kind === "learned"));
  const fromProfile = drafts.filter(d => !isCover(d) && !needs.includes(d) && !written.includes(d));
  const unapproved = fromProfile.filter(d => !d.verdict && !d.final_answer).length;
  const lastShot = runs.find(x => x.screenshot);
  const applied = job.status === "submitted";
  const byKind = Object.fromEntries(sections.map(s => [s.kind, s]));
  const people = res.people ?? [];

  const f = r.facts;
  const where = job.locations.length ? job.locations.slice(0, 2).join("; ") + (job.locations.length > 2 ? ` +${job.locations.length - 2}` : "") : "";
  const facts: [string, string][] = ([["dollar", f?.pay], ["level", f?.level], ["pin", where], ["globe", f?.mode],
    ["doc", f?.category], ["passport", f?.sponsorship || (f?.degree ? `${f.degree} required` : "")]] as [string, string | undefined][])
    .filter(([, v]) => !!v) as [string, string][];
  const stage = applied ? (job.outcome ? OUTCOME_LABEL[job.outcome] : "Applied") : job.status === "filled" || job.status === "error" ? "Needs you"
    : r.busy ? "Working on it" : job.status === "skipped" ? "Skipped" : job.status === "left_out" ? "Left out" : "";

  return (
    <div className={`jobview ${embedded ? "embedded" : "page"}`}>
      {!embedded && <a className="back" href="#/matches"><Icon name="back" size={14} />Matches</a>}

      <header className="jv-top">
        <Logo name={job.company} size={40} />
        <div className="grow">
          <a className="co" href={companyHref(job.company)}>{job.company}</a>
          {res.what_the_team_builds && <p className="muted tagline clamp1">{res.what_the_team_builds}</p>}
        </div>
        <div className="jv-actions">
          <a className="btn ghost sm" href={job.url} target="_blank" rel="noreferrer" title="Open the posting"><Icon name="ext" size={14} />Posting</a>
          {!applied && (job.status === "filled" || !r.can_fill) && <button className="btn ghost sm" onClick={() => act("submitted")}>Mark applied</button>}
          <button className={`btn ghost sm ${job.verdict === "red" ? "on" : ""}`} onClick={() => act("verdict", { verdict: job.verdict === "red" ? null : "red" })}>Not for me</button>
          {applied ? null : r.busy ? <span className="btn sm" aria-busy><Dots />{r.busy === "filling" ? "Filling" : "Drafting"}</span> : (<>
            {drafts.length > 0 && r.can_fill && <button className="btn sm" onClick={() => act("fill", { submit: false })}>Fill, I'll submit</button>}
            <button className="btn primary sm" onClick={autopilot}>{unsure || ["skipped", "left_out"].includes(job.status) ? "Apply anyway" : "Apply"}</button>
          </>)}
        </div>
      </header>
      <h1 className="jv-title">{job.title}{embedded && <a className="small jv-open" href={`#/job/${id}`}>Full page</a>}</h1>
      <div className="jv-tags">
        {stage && <span className={`tag ${applied ? "ok" : stage === "Needs you" ? "warn" : ""}`}>{stage}</span>}
        {job.terms.map(t => <span key={t} className="tag">{t}</span>)}
        {job.date_posted && <span className="tag quiet">Posted {ago(job.date_posted)}</span>}
        {match.score != null && <span className="tag quiet">Resume match {match.matched.length}/{match.total}</span>}
        <span className="tag quiet">via {job.ats}</span>
      </div>
      {facts.length > 0 && <dl className="jv-facts">{facts.map(([icon, v]) => (
        <div key={icon}><dt><Icon name={icon} size={15} /></dt><dd>{v}</dd></div>))}</dl>}

      {status && !status.llm.ok && <p className="note warn">No AI is connected, so only answers from your profile get filled. <a href="#/settings">Choose an AI</a>.</p>}
      {job.status === "left_out" && <p className="note">{job.hold_reason}. Autopilot won't apply to this role; Apply anyway is your call.</p>}
      {unsure && !applied && <p className="note warn"><strong>You may not qualify.</strong> {eligibility.reasons.join(" ")} Autopilot skips roles like this; Apply anyway is your call.</p>}
      {gate && !applied && !["skipped", "left_out"].includes(job.status) && (
        <details className="note gate"><summary>{gate.summary}</summary>
          {gate.for.length + gate.against.length > 0 ? <ul className="gate-why">
            {gate.for.map(x => <li key={"+" + x}><span className="ok-text" aria-label="counts for">+</span> {x}</li>)}
            {gate.against.map(x => <li key={"-" + x}><span className="warn-text" aria-label="counts against">−</span> {x}</li>)}
          </ul> : <p className="small muted">No reasons recorded yet.</p>}
        </details>)}
      {trap && !applied && !(job.hold_reason ?? "").includes(trap) && <p className="note warn">{trap}{posting_marked && <> <button className="link" onClick={showTrap}>Show it in the posting</button></>}</p>}
      {ai_policy && !applied && !(job.hold_reason ?? "").includes(ai_policy) && <p className="note warn">{ai_policy}</p>}
      {approval && <FirstRun id={id} company={job.company} a={approval} hold={job.hold_reason} onDone={() => { refresh(); load(); }} />}
      {job.hold_reason && job.status === "filled" && !approval && <p className="note warn">Held for you: {job.hold_reason}{posting_marked && trap && job.hold_reason.includes(trap) && <> <button className="link" onClick={showTrap}>Show it in the posting</button></>}</p>}
      {job.error && !/connect/i.test(job.error) && <p className="note warn">{friendly(job.error)}</p>}

      <div className="tabs jv-tabs" role="tablist">
        {([["overview", "Overview"], ["company", "Company"], ["application", `Application${drafts.length ? ` (${drafts.length})` : ""}`]] as [typeof tab, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>))}
      </div>
      <div className="jv-body">
        <div className="jv-main">
          <LivePeek id={id} company={job.company} approve={!!approval} />
          {tab === "overview" && <>

          <section className="block">
            <div className="sub-h"><h3>About the job</h3>
              {(job.description || posting_marked) && <div className="seg mini" role="tablist">
                <button role="tab" aria-selected={!fullPosting} className={!fullPosting ? "on" : ""} onClick={() => setFullPosting(false)}>Summary</button>
                <button role="tab" aria-selected={fullPosting} className={fullPosting ? "on" : ""} onClick={() => setFullPosting(true)}>Full posting</button></div>}</div>
            {fullPosting ? (posting_marked
              // The whole posting as the employer wrote it, hidden lines included, each line aimed at AI marked.
              ? <pre className="posting">{posting_marked.map((seg, i) => seg.trap
                  ? <mark key={i} className="trap">{seg.text}<small>{seg.trap.attention ? "may be an attention check for you"
                      : seg.trap.how === "visible" ? "aimed at AI tools" : `hidden: ${seg.trap.how}`}</small></mark>
                  : seg.text)}</pre>
              : <pre className="posting">{job.description}</pre>) : (<>
              {res.summary && <p>{res.summary}</p>}
              {SECTION_ORDER.filter(k => byKind[k]).map(k => (
                <div key={k}><h4>{SECTION_TITLE[k]}</h4><ul>{byKind[k].items.map((t, i) => <li key={i}>{t}</li>)}</ul></div>))}
              {!res.summary && sections.length === 0 && (job.description
                ? <pre className="posting">{job.description.slice(0, 1600)}{job.description.length > 1600 ? "…" : ""}</pre>
                : <p className="muted">Jobsmith reads the posting when it drafts or applies.</p>)}
            </>)}
          </section>

          <section className="block">
            <h3>Your resume against it</h3>
            {match.score == null ? <p className="muted">No posting text yet.</p> : (<>
              <p><MatchText score={match.score} matched={match.matched.length} total={match.total} /> this posting asks for are on your resume.</p>
              {match.matched.length > 0 && <p className="small"><span className="muted">On it:</span> {match.matched.join(", ")}</p>}
              {match.missing.length > 0 && <p className="small"><span className="muted">Missing:</span> {match.missing.join(", ")}</p>}
            </>)}
            {res.fit_angles && res.fit_angles.length > 0 && <ul className="small">{res.fit_angles.map(a => <li key={a.angle}>{a.angle}</li>)}</ul>}
          </section>

          </>}
          {tab === "company" && (
            <section className="block">
              <h3>{job.company}</h3>
              {res.what_the_team_builds && <p>{res.what_the_team_builds}</p>}
              {res.values_and_culture ? <p>{res.values_and_culture}</p> : !res.what_the_team_builds && <p className="muted">Researched the first time Jobsmith applies here.</p>}
              {res.tech_stack && res.tech_stack.length > 0 && <><h4>Stack</h4><p>{res.tech_stack.join(", ")}</p></>}
              {res.red_flags && res.red_flags.length > 0 && <><h4>Worth knowing</h4><p>{res.red_flags.join(" ")}</p></>}
              <p><a href={companyHref(job.company)}>Every role at {job.company}</a></p>
            </section>)}
          {tab === "application" && <>
          <AuditTrail id={id} refresh={job.status} />
          <section className="block">
            <div className="sub-h"><h3>Your answers{drafts.length - (cover ? 1 : 0) ? ` (${drafts.length - (cover ? 1 : 0)})` : ""}</h3>
              {drafts.length > 0 && !r.busy && <button className="link small" onClick={() => act("prepare")}>Redraft</button>}</div>
            {drafts.length === 0 ? (
              <p className="muted">Drafted when it applies. <button className="link" onClick={() => act("prepare")} disabled={!!r.busy}>Draft now</button></p>
            ) : (<>
              {readiness && !readiness.ready && !applied && (
                <p className="small muted">Autopilot would stop on {readiness.blockers.length}: {readiness.blockers.slice(0, 3).join("; ")}{readiness.blockers.length > 3 ? "; and more" : ""}.</p>)}
              {needs.length > 0 && (<details open={needs.length <= 6}><summary>Needs you ({needs.length})</summary>
                <ul className="answers">{needs.map(d => <AnswerRow key={d.id} d={d} onChange={load} />)}</ul></details>)}
              {written.length > 0 && (<details open={!embedded}><summary>Written for this job ({written.length})</summary>
                <ul className="answers">{written.map(d => <AnswerRow key={d.id} d={d} onChange={load} />)}</ul></details>)}
              {fromProfile.length > 0 && (<details><summary>From your profile ({fromProfile.length})</summary>
                <ProfileAnswers rows={fromProfile} onChange={load} approveAll={unapproved ? () => act("approve-standard") : undefined} /></details>)}
            </>)}
          </section>

          <CoverLetter id={id} d={cover} busy={!!r.busy} onChange={load} />
          </>}
        </div>

        <aside className="jv-rail">
          <section className="rail-card">
            <h3>Get referred for this role</h3>
            {connections.length === 0 && people.length === 0 && (
              <p className="small muted">No one yet. <a href="#/profile">Import LinkedIn</a> to see who you know here.</p>)}
            {connections.length > 0 && (<>
              <p className="rail-h">You know</p>
              <ul className="people">{connections.map(p => (
                <li key={p.url || p.first_name + p.last_name}><a href={p.url} target="_blank" rel="noreferrer">{p.first_name} {p.last_name}</a>
                  <span className="muted small clamp1">{p.position}</span></li>))}</ul></>)}
            {people.length > 0 && (<>
              <p className="rail-h">Hiring managers and alumni</p>
              <ul className="people">{people.map(p => (
                <li key={p.name}>{p.source_url ? <a href={p.source_url} target="_blank" rel="noreferrer">{p.name}</a> : <strong>{p.name}</strong>}
                  <span className="muted small clamp1">{p.role}</span></li>))}</ul></>)}
            <details><summary className="small">{job.referral_name ? `Referred by ${job.referral_name}` : "Someone referred you?"}</summary><Referral job={job} onSaved={load} /></details>
          </section>

          {runs.length > 0 && (
            <section className="rail-card">
              <details><summary><h3 className="inline">History</h3>{usage.tokens ? <span className="small muted"> {tok(usage.tokens)} tokens</span> : null}</summary>
                <ul className="hist">{runs.slice(0, 6).map(x => (
                  <li key={x.id}><strong>{x.kind === "fill" ? "Filled" : x.kind === "draft" ? "Drafted" : x.kind === "submit" ? "Submitted" : x.kind}</strong>
                    <span className="muted small"> {ago(x.started_at)}</span>
                    <details><summary className="small">Log</summary><pre className="log">{x.log}</pre></details></li>))}</ul>
                {lastShot && <a className="small" href={`/api/runs/${lastShot.id}/screenshot`} target="_blank" rel="noreferrer">Screenshot of the filled form</a>}
              </details>
            </section>)}
        </aside>
      </div>
    </div>
  );
}
