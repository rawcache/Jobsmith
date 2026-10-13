import { useContext, useEffect, useState } from "react";
import { ago, api, Job, OUTCOME_LABEL } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo, MatchText } from "../ui";
import JobPage from "./JobDetail";

type Resp = { total: number; jobs: Job[]; facets: { category: { category: string; n: number }[] } };
const VIEWS: [string, string][] = [
  ["new,fetched,drafted,filled,error", "To apply"], ["filled,error", "Needs you"], ["submitted", "Applied"],
  ["skipped", "Skipped"], ["", "All"],
];

function stateLine(j: Job, busy?: string) {
  if (busy) return <span className="accent-text"><Dots />{busy === "drafting" ? "Researching" : "Applying"}</span>;
  if (j.status === "submitted") return <span className="ok-text">Applied{j.outcome ? `, ${OUTCOME_LABEL[j.outcome].toLowerCase()}` : ""}</span>;
  if (j.status === "filled") return <span className="warn-text">Needs one click</span>;
  if (j.status === "error") return <span className="warn-text">Needs you</span>;
  if (j.status === "skipped") return <span className="muted">Skipped</span>;
  return null;
}

export default function Matches({ selected }: { selected?: string }) {
  const { status, refresh } = useContext(StatusCtx);
  const [data, setData] = useState<Resp | null>(null);
  const [f, setF] = useState({ q: "", category: "", status: VIEWS[0][0], min_score: "40", term: "" });
  const [limit, setLimit] = useState(60);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState("");

  const load = () => api.get<Resp>(`/api/jobs?${new URLSearchParams({ ...f, limit: String(limit) })}`).then(setData).catch(e => setMsg(e.message));
  useEffect(() => { load(); }, [f, limit]);
  useEffect(() => { const t = setInterval(load, 6000); return () => clearInterval(t); }, [f, limit]);
  const current = selected ?? data?.jobs[0]?.id;
  const [narrow, setNarrow] = useState(() => matchMedia("(max-width: 820px)").matches);
  useEffect(() => { const m = matchMedia("(max-width: 820px)"); const on = () => setNarrow(m.matches); m.addEventListener("change", on); return () => m.removeEventListener("change", on); }, []);

  const run = async (action: string, ids: string[]) => {
    const r = await api.post<{ started: number }>("/api/jobs/batch", { action, ids });
    setMsg(action === "skip" ? `Skipped ${ids.length}.` : `Autopilot is applying to ${r.started}.`);
    setSel(new Set()); refresh(); load();
  };
  const toggle = (id: string) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  if (narrow && selected) return <JobPage id={selected} />;
  return (
    <div className="matches">
      <div className="mx-top">
        <h1>Matches</h1>
        <p className="muted">{data ? `${data.total.toLocaleString()} roles from your job lists, best fit first.` : "Loading"}</p>
      </div>
      <div className="mx-filters">
        <label className="search"><Icon name="search" size={16} /><input placeholder="Search company or title" value={f.q} onChange={set("q")} /></label>
        <select value={f.status} onChange={set("status")} aria-label="Show">{VIEWS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select>
        <select value={f.category} onChange={set("category")} aria-label="Category">
          <option value="">All categories</option>
          {data?.facets.category.map(c => <option key={c.category} value={c.category}>{c.category || "Other"} ({c.n})</option>)}
        </select>
        <select value={f.term} onChange={set("term")} aria-label="Season">
          <option value="">Any season</option>
          {["Summer 2027", "New Grad", "Fall 2026", "Spring 2027"].map(t => <option key={t}>{t}</option>)}
        </select>
        <label className="fitmin">Fit at least <input type="number" min={0} max={100} value={f.min_score} onChange={set("min_score")} /></label>
      </div>
      {msg && <p className="note">{msg}</p>}
      {sel.size > 0 && (
        <div className="selbar">
          <span>{sel.size} selected</span>
          <button className="btn primary sm" onClick={() => run("autopilot", [...sel])}>Apply to {sel.size} with autopilot</button>
          <button className="btn sm" onClick={() => run("prepare", [...sel])}>Just draft</button>
          <button className="link" onClick={() => run("skip", [...sel])}>Skip</button>
          <button className="link" onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}

      <div className="split">
        <ul className="mx-list" aria-label="Roles">
          {data?.jobs.map(j => (
            <li key={j.id} className={j.id === current ? "on" : ""}>
              <input type="checkbox" checked={sel.has(j.id)} onChange={() => toggle(j.id)} aria-label={`Select ${j.company} ${j.title}`} />
              <a href={`#/matches/${j.id}`} className="mx-item">
                <Logo name={j.company} size={40} />
                <div className="grow">
                  <strong className="mx-title">{j.title}</strong>
                  <span className="mx-co">{j.company}</span>
                  <span className="mx-meta">{j.locations[0] ?? ""}{j.locations.length > 1 ? ` and ${j.locations.length - 1} more` : ""}
                    {j.date_posted ? `, ${ago(j.date_posted)}` : ""}</span>
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
        </ul>
        <div className="mx-detail">
          {current ? <JobPage id={current} embedded /> : <p className="muted pad">Pick a role to see it here.</p>}
        </div>
      </div>
    </div>
  );
}
