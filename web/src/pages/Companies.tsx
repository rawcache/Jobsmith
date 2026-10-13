import { useEffect, useState } from "react";
import { api, companyHref } from "../api";
import { Icon, Logo } from "../ui";

type Row = { company: string; jobs: number; applied: number; best: number | null; connections: number; domain: string };

export default function Companies() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => { const t = setTimeout(() => api.get<Row[]>(`/api/companies?q=${encodeURIComponent(q)}`).then(setRows), 200); return () => clearTimeout(t); }, [q]);
  return (
    <div className="page">
      <div className="page-h"><div><h1>Companies</h1></div></div>
      <div className="filters"><label className="search"><Icon name="search" size={16} /><input placeholder="Search companies" value={q} onChange={e => setQ(e.target.value)} /></label></div>
      <ul className="co-grid">
        {rows?.map(r => (
          <li key={r.company}><a className="card co-card" href={companyHref(r.company)}>
            <Logo name={r.company} size={44} domain={r.domain} />
            <div className="grow"><strong>{r.company}</strong>
              <p className="small muted">{r.jobs} role{r.jobs > 1 ? "s" : ""}{r.applied ? `, applied to ${r.applied}` : ""}</p></div>
            {r.connections > 0 && <span className="accent-text small">{r.connections} you know</span>}
          </a></li>))}
      </ul>
      {rows && rows.length === 0 && <p className="card muted">No companies yet. Add a job list on the Autopilot page.</p>}
    </div>
  );
}
