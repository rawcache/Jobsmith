import { useContext, useEffect, useState } from "react";
import { ago, api, Job, OUTCOME_LABEL } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, MatchText, poll } from "../ui";
import JobPage from "./JobDetail";

type Resp = { total: number; jobs: Job[]; facets: { category: { category: string; n: number }[] }; left_out: number };
const VIEWS: [string, string][] = [
  ["new,fetched,drafted,filled,error", "To apply"], ["filled,error", "Needs you"], ["submitted", "Applied"],
  ["skipped", "Skipped"], ["", "All"],
];

function stateLine(j: Job, busy?: string) {
  if (busy) return <span className="accent-text"><Dots />{busy === "drafting" ? "Researching" : "Applying"}</span>;
  if (j.status === "submitted") return <span className="ok-text">Applied{j.outcome ? `, ${OUTCOME_LABEL[j.outcome].toLowerCase()}` : ""}</span>;
  if (j.status === "filled") return <span className="warn-text">Needs one click</span>;
  if (j.status === "error") return <span className="warn-text">Needs you</span>;
  if (j.status === "skipped") return <span className="muted" title={j.hold_reason ?? ""}>Skipped{j.eligibility && j.eligibility.ok === false ? ": may not qualify" : ""}</span>;
  if (j.eligibility && j.eligibility.ok === false) return <span className="muted" title={(j.eligibility.reasons ?? []).join(" ")}>May not qualify</span>;
  if (j.gate && !j.gate.passed) return <span className="muted" title={j.gate.summary}>{j.gate.score == null ? "Not scored yet" : "Under your fit bar"}</span>;
  return null;
}

/** Job board roles screened out for you (senior title, years asked, pay), kept so you can still apply anyway.
 *  Autopilot never picks them up. Collapsed: they're there for a second look, not to work through. */
function LeftOut({ n, current, apply }: { n: number; current?: string; apply: (id: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [limit, setLimit] = useState(100);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!open) return;
    let current = true, sent = 0, shown = 0;     // a slower, older answer mustn't replace a newer one
    const load = () => {
      const n = ++sent;
      return api.get<Resp>(`/api/jobs?status=left_out&limit=${limit}`).then(r => {
        if (current && n > shown) { shown = n; setJobs(r.jobs); }
      });
    };
    load();
    const t = poll(load, 6000);                  // a sync can swap roles without changing the count
    return () => { current = false; t.stop(); };
  }, [open, n, limit, tick]);
  if (!n) return null;
  return (
    <li className="mx-leftout">
      <details open={open} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Left out ({n})</summary>
        <p className="small muted">Roles from job boards that ask for more than your profile shows or pay under your
          minimum. Autopilot won't apply to them.</p>
        {open && !jobs && <p className="small muted"><Dots />Loading</p>}
        <ul>{jobs?.map(j => (
          <li key={j.id} className={j.id === current ? "on" : ""}>
            <a href={`#/matches/${j.id}`} className="grow">
              <strong className="mx-title">{j.title}</strong> <span className="mx-co">{j.company}</span>
              <span className="mx-meta">{(j.hold_reason ?? "").replace(/^Left out: /, "")}</span>
            </a>
            <button className="btn sm" onClick={() => apply(j.id).then(() => setTick(t => t + 1))}>Apply anyway</button>
          </li>))}
        </ul>
        {jobs && n > jobs.length && <button className="link" onClick={() => setLimit(limit + 100)}>Show {Math.min(100, n - jobs.length)} more</button>}
      </details>
    </li>
  );
}

export default function Matches({ selected }: { selected?: string }) {
  const { status, refresh } = useContext(StatusCtx);
  const [data, setData] = useState<Resp | null>(null);
  const [f, setF] = useState({ q: "", category: "", status: VIEWS[0][0], min_score: "40", term: "", location: "", sort: "score" });
  const [limit, setLimit] = useState(60);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState("");

  const load = () => api.get<Resp>(`/api/jobs?${new URLSearchParams({ ...f, limit: String(limit) })}`).then(setData).catch(e => setMsg(e.message));
  useEffect(() => { load(); }, [f, limit]);
  useEffect(() => { const t = poll(load, 6000); return () => t.stop(); }, [f, limit]);
  const current = selected ?? data?.jobs[0]?.id;
  const [narrow, setNarrow] = useState(() => matchMedia("(max-width: 820px)").matches);
  useEffect(() => { const m = matchMedia("(max-width: 820px)"); const on = () => setNarrow(m.matches); m.addEventListener("change", on); return () => m.removeEventListener("change", on); }, []);

  const run = async (action: string, ids: string[]) => {
    const r = await api.post<{ started: number }>("/api/jobs/batch", { action, ids });
    setMsg(action === "skip" ? `Skipped ${ids.length}.` : action === "prepare" ? `Drafting ${r.started}.` :
      `Applying to ${r.started}. You can watch each one fill on the Autopilot page.`);
    setSel(new Set()); refresh(); load();
  };
  const toggle = (id: string) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  if (narrow && selected) return <JobPage id={selected} />;
  return (
    <div className="matches">
      <div className="mx-filters">
        <label className="search"><Icon name="search" size={15} /><input placeholder="Find a role or company" value={f.q} onChange={set("q")} /></label>
        <select className="filter" value={f.location} onChange={set("location")} aria-label="Location">
          <option value="">Location</option>{["Remote", "New York", "San Francisco", "Seattle", "Boston", "Austin", "Atlanta", "Chicago", "Los Angeles", "Canada", "London"].map(l => <option key={l}>{l}</option>)}
        </select>
        <select className="filter" value={f.term} onChange={set("term")} aria-label="Job type">
          <option value="">Job type</option>{["Summer 2027", "New Grad", "Fall 2026", "Spring 2027"].map(t => <option key={t}>{t}</option>)}
        </select>
        <select className="filter" value={f.category} onChange={set("category")} aria-label="Category">
          <option value="">Category</option>
          {data?.facets.category.map(c => <option key={c.category} value={c.category}>{c.category || "Other"} ({c.n})</option>)}
        </select>
        <select className="filter" value={f.status} onChange={set("status")} aria-label="Show">{VIEWS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select>
        <label className="fitmin">Fit ≥ <input type="number" min={0} max={100} value={f.min_score} onChange={set("min_score")} /></label>
      </div>
      {msg && <p className="note">{msg}</p>}
      {sel.size === 0 && data && data.jobs.some(j => ["new", "fetched", "drafted"].includes(j.status) && !status?.active[j.id]) && (
        <div className="selbar quiet">
          <label className="check"><input type="checkbox" onChange={e => setSel(e.target.checked ? new Set(data.jobs.filter(j => ["new", "fetched", "drafted"].includes(j.status)).map(j => j.id)) : new Set())} />Select all shown</label>
          <button className="btn sm" onClick={() => run("autopilot", data.jobs.filter(j => ["new", "fetched", "drafted"].includes(j.status) && !status?.active[j.id]).slice(0, 10).map(j => j.id))}>
            Apply to the top 10</button>
          <span className="small muted">Several fill at once (set how many in Settings).</span>
        </div>
      )}
      {sel.size > 0 && (
        <div className="selbar">
          <span>{sel.size} selected</span>
          <button className="btn primary sm" onClick={() => run("autopilot", [...sel])}>Apply to {sel.size} at once</button>
          <button className="btn sm" onClick={() => run("prepare", [...sel])}>Just draft</button>
          <button className="link" onClick={() => run("skip", [...sel])}>Skip</button>
          <button className="link" onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}

      <div className="split">
        <ul className="mx-list" aria-label="Roles">
          <li className="mx-head"><span className="small muted">Found {data?.total.toLocaleString() ?? "…"} roles</span>
            <select className="sortsel" value={f.sort} onChange={set("sort")} aria-label="Sort">
              <option value="score">Best fit</option><option value="posted">Newest</option><option value="company">Company</option></select></li>
          {data?.jobs.map(j => (
            <li key={j.id} className={j.id === current ? "on" : ""}>
              <input type="checkbox" checked={sel.has(j.id)} onChange={() => toggle(j.id)} aria-label={`Select ${j.company} ${j.title}`} />
              <a href={`#/matches/${j.id}`} className="mx-item">
                <Logo name={j.company} size={34} />
                <div className="grow">
                  <strong className="mx-title">{j.title}</strong>
                  <span className="mx-co">{j.company}</span>
                  <span className="mx-meta">{j.locations[0] ?? ""}{j.locations.length > 1 ? ` +${j.locations.length - 1}` : ""}</span>
                  <span className="mx-meta mono">{[j.pay, j.date_posted ? ago(j.date_posted) : ""].filter(Boolean).join("  ")}{j.fit_score != null ? `  fit ${Math.round(j.fit_score)}` : ""}</span>
                  <span className="mx-meta">
                    {j.match != null && <MatchText score={j.match} matched={j.match_hits} total={j.match_total} />}
                    {(j.connections ?? 0) > 0 && <span className="accent-text">{j.match != null ? ". " : ""}{j.connections} you know</span>}
                  </span>
                  {stateLine(j, status?.active[j.id])}
                </div>
              </a>
            </li>
          ))}
          {data && data.jobs.length === 0 && <li className="empty-li">No roles here. Add a job list on the Autopilot page or loosen the filters.</li>}
          {data && data.total > data.jobs.length && (
            <li className="empty-li"><button className="link" onClick={() => setLimit(limit + 60)}>Show {Math.min(60, data.total - data.jobs.length)} more</button></li>
          )}
          {data && <LeftOut n={data.left_out} current={current} apply={id => run("autopilot", [id])} />}
        </ul>
        <div className="mx-detail">
          {current ? <JobPage id={current} embedded /> : <p className="muted pad">Pick a role to see it here.</p>}
        </div>
      </div>
    </div>
  );
}
