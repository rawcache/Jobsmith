import { Fragment, useEffect, useState } from "react";
import { ago, api, Person } from "../api";
import { Dots, Icon, Logo } from "../ui";

type Draft = { id: number; person: string; kind: string; text: string; sent_at: number | null; created_at: number };
type Co = { company: string; job_id: string; title: string; status: string; people: Person[]; drafts: Draft[] };
type Resp = { companies: Co[]; kinds: Record<string, string>; network: number };

/** People you know at the companies you're applying to, and a drafted message for each. You send them yourself. */
export default function Outreach({ company }: { company?: string }) {
  const [d, setD] = useState<Resp | null>(null);
  const [open, setOpen] = useState<string | undefined>(company);
  const load = () => api.get<Resp>("/api/outreach").then(setD);
  useEffect(() => { load(); }, []);
  if (!d) return <div className="page"><p className="muted"><Dots />Loading</p></div>;
  return (
    <div className="page">
      <div className="page-h"><div><h1>Outreach</h1>
        <p className="muted">Drafts for asking a referral or saying hello to a recruiter. Copy one and send it yourself; Jobsmith never sends messages.</p></div></div>
      {d.network === 0 ? (
        <section className="card empty-card"><h2>Import your LinkedIn connections first</h2>
          <p className="small">LinkedIn: Settings, Data privacy, Get a copy of your data, Connections. Then add the file in <a href="#/profile">Profile</a>.</p></section>
      ) : d.companies.length === 0 ? <p className="muted">None of your connections work at the companies you're applying to yet.</p> : (
        <div className="table-card">
          <table className="dtable">
            <thead><tr><th>Company</th><th>Role</th><th>People you know</th><th>Drafts</th><th /></tr></thead>
            <tbody>{d.companies.map(c => (<Fragment key={c.company}>
              <tr className={open === c.company ? "on" : ""} onClick={() => setOpen(o => o === c.company ? undefined : c.company)}>
                <td><span className="cell-co"><Logo name={c.company} size={20} />{c.company}</span></td>
                <td className="clamp1">{c.title}</td>
                <td className="mono">{c.people.length}</td>
                <td className="mono">{c.drafts.length || ""}</td>
                <td className="right"><Icon name="down" size={14} /></td>
              </tr>
              {open === c.company && <tr className="expand"><td colSpan={5}><People c={c} kinds={d.kinds} onChange={load} /></td></tr>}
            </Fragment>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}

function People({ c, kinds, onChange }: { c: Co; kinds: Record<string, string>; onChange: () => void }) {
  const [busy, setBusy] = useState("");
  const [out, setOut] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState("");
  const draft = async (p: Person, kind: string) => {
    const k = `${p.first_name} ${p.last_name}`;
    setBusy(k + kind);
    const r = await api.post<{ text: string }>("/api/outreach/draft", { job_id: c.job_id, person: p, kind });
    setOut(o => ({ ...o, [k]: r.text })); setBusy(""); onChange();
  };
  const copy = async (k: string, t: string) => { try { await navigator.clipboard.writeText(t); setCopied(k); setTimeout(() => setCopied(""), 1500); } catch { /* select by hand */ } };
  return (
    <div className="people-grid">
      {c.people.map(p => { const k = `${p.first_name} ${p.last_name}`; const prior = c.drafts.find(x => x.person === k); const text = out[k] ?? prior?.text; return (
        <div key={k} className="person">
          <div className="person-h"><div className="grow"><a href={p.url} target="_blank" rel="noreferrer"><strong>{k}</strong></a>
            <p className="small muted">{p.position}</p></div>
            {prior && <span className="tag quiet">{prior.sent_at ? `Sent ${ago(prior.sent_at)}` : `Drafted ${ago(prior.created_at)}`}</span>}</div>
          <div className="row tight">{Object.entries(kinds).map(([kind, label]) => (
            <button key={kind} className="btn sm" disabled={!!busy} onClick={() => draft(p, kind)}>{busy === k + kind ? <Dots /> : label}</button>))}</div>
          {text && (<>
            <textarea className="draft-box" defaultValue={text} key={text} rows={5} />
            <div className="row tight">
              <button className="btn primary sm" onClick={() => copy(k, text)}>{copied === k ? "Copied" : "Copy"}</button>
              {p.url && <a className="btn ghost sm" href={p.url} target="_blank" rel="noreferrer">Open their LinkedIn</a>}
              {prior && !prior.sent_at && <button className="btn ghost sm" onClick={() => api.post(`/api/outreach/${prior.id}/sent`, { sent: true }).then(onChange)}>I sent it</button>}
            </div></>)}
        </div>); })}
    </div>
  );
}
