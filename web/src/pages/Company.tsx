import { useContext, useEffect, useState } from "react";
import { ago, api, Job, OUTCOME_LABEL, Person, Research } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo } from "../ui";

type C = { name: string; domain: string; jobs: (Job & { outcome?: string | null })[]; research: Research;
  connections: Person[]; applied: number; open: number };

export default function Company({ name }: { name: string }) {
  const { refresh } = useContext(StatusCtx);
  const [c, setC] = useState<C | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.get<C>(`/api/companies/${encodeURIComponent(name)}`).then(setC).catch(e => setErr(e.message));
  useEffect(() => { setC(null); load(); }, [name]);
  if (err) return <div className="page"><a className="back" href="#/companies"><Icon name="back" size={15} />Companies</a><p className="card">{err}</p></div>;
  if (!c) return <div className="page"><p className="muted"><Dots /> Loading</p></div>;
  const r = c.research;
  const openJobs = c.jobs.filter(j => !["submitted", "skipped"].includes(j.status));
  const applyAll = async () => {
    const res = await api.post<{ started: number }>("/api/jobs/batch", { action: "autopilot", ids: openJobs.map(j => j.id) });
    setMsg(`Autopilot started ${res.started} application${res.started === 1 ? "" : "s"} at ${c.name}.`); refresh(); load();
  };

  return (
    <div className="page">
      <a className="back" href="#/companies"><Icon name="back" size={15} />Companies</a>
      <div className="layout-side">
        <div className="col-main">
          <section className="card co-head">
            <Logo name={c.name} size={72} domain={c.domain} />
            <div className="grow">
              <h1>{c.name}</h1>
              {r.what_the_team_builds ? <p className="muted">{r.what_the_team_builds}</p> : null}
              <div className="row tight">
                <a className="btn sm" href={`https://${c.domain}`} target="_blank" rel="noreferrer"><Icon name="ext" size={14} />Website</a>
                <a className="btn sm" href={`https://www.linkedin.com/company/${c.domain.replace(".com", "")}`} target="_blank" rel="noreferrer"><Icon name="linkedin" size={14} />LinkedIn</a>
              </div>
            </div>
            {openJobs.length > 0 && <button className="btn primary" onClick={applyAll}>Apply to {openJobs.length} open role{openJobs.length > 1 ? "s" : ""}</button>}
          </section>
          {msg && <p className="toast" role="status">{msg}</p>}

          <section className="card prose">
            <h2>Overview</h2>
            {r.summary ? <p>{r.summary}</p> : <p className="muted">Jobsmith researches {c.name} the first time it applies here. The overview, people and news show up after that.</p>}
            {r.values_and_culture && <p>{r.values_and_culture}</p>}
            {r.tech_stack && r.tech_stack.length > 0 && <p><span className="muted">Stack:</span> {r.tech_stack.join(", ")}.</p>}
          </section>

          <section className="card">
            <div className="card-h"><h2>Get referred to {c.name}</h2><span className="muted small">People who could refer or advise you. Jobsmith never messages anyone.</span></div>
            <div className="ref-grid">
              <div className="ref-col">
                <h3>Your connections <span className="muted"> ({c.connections.length})</span></h3>
                {c.connections.length === 0 ? <p className="small muted">None found. <a href="#/profile">Import your LinkedIn connections</a> to see them here.</p> : (
                  <ul className="people">{c.connections.slice(0, 12).map(p => (
                    <li key={p.url || p.first_name + p.last_name}>
                      <div className="grow"><a href={p.url} target="_blank" rel="noreferrer">{p.first_name} {p.last_name}</a>
                        <p className="small muted clamp1">{p.position}</p></div></li>))}
                  </ul>)}
              </div>
              <div className="ref-col">
                <h3>Hiring managers and alumni <span className="muted"> ({r.people?.length ?? 0})</span></h3>
                {!r.people?.length ? <p className="small muted">None found yet.</p> : (
                  <ul className="people">{r.people.map(p => (
                    <li key={p.name}>
                      <div className="grow">{p.source_url ? <a href={p.source_url} target="_blank" rel="noreferrer">{p.name}</a> : <strong>{p.name}</strong>}
                        <p className="small muted">{p.role}{p.why_relevant ? `. ${p.why_relevant}` : ""}</p></div></li>))}
                  </ul>)}
              </div>
            </div>
          </section>

          {(r.fit_angles?.length || r.red_flags?.length) ? (
            <section className="card prose">
              <h2>Jobsmith's take for you</h2>
              {r.fit_angles && r.fit_angles.length > 0 && (<><h3 className="ok-text">Where you fit</h3><ul>{r.fit_angles.map(a => <li key={a.angle}>{a.angle}</li>)}</ul></>)}
              {r.red_flags && r.red_flags.length > 0 && (<><h3 className="warn-text">Worth knowing</h3><ul>{r.red_flags.map(a => <li key={a}>{a}</li>)}</ul></>)}
            </section>
          ) : null}

          {r.recent_news && r.recent_news.length > 0 && (
            <section className="card">
              <h2>Recent news</h2>
              <ul className="news">{r.recent_news.map(n => <li key={n.url}><a href={n.url} target="_blank" rel="noreferrer">{n.headline}</a>
                <span className="small muted">{n.url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]}</span></li>)}</ul>
            </section>
          )}
        </div>

        <aside className="col-side">
          <section className="card side-card">
            <h2>You and {c.name}</h2>
            <dl className="facts-dl">
              <div><dt>Open roles for you</dt><dd>{c.open}</dd></div>
              <div><dt>Applied</dt><dd>{c.applied}</dd></div>
              <div><dt>People you know</dt><dd>{c.connections.length}</dd></div>
            </dl>
          </section>
          <section className="card side-card">
            <h2>Roles at {c.name}</h2>
            <ul className="mini-jobs">
              {c.jobs.map(j => (
                <li key={j.id}><a href={`#/job/${j.id}`}>
                  <div className="grow"><strong>{j.title}</strong>
                    <p className="small muted">{j.terms.join(", ")}{j.locations[0] ? `${j.terms.length ? ", " : ""}${j.locations[0]}` : ""}{j.date_posted ? `, ${ago(j.date_posted)}` : ""}</p></div>
                  {j.status === "submitted" ? <span className="ok-text small">{j.outcome ? OUTCOME_LABEL[j.outcome] : "Applied"}</span>
                    : <span className="muted small">Fit {Math.round(j.fit_score ?? 0)}</span>}
                </a></li>))}
            </ul>
            
          </section>
        </aside>
      </div>
    </div>
  );
}
