import { useContext, useEffect, useState } from "react";
import { api, companyHref, Job } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon, Logo } from "../ui";

type Resp = { jobs: Job[] };
const COLS: { key: string; title: string; hint: string; test: (j: Job, busy: boolean) => boolean }[] = [
  { key: "working", title: "In progress", hint: "", test: (j, b) => b || ["drafted", "filling"].includes(j.status) },
  { key: "review", title: "Needs one click", hint: "", test: j => ["filled", "error"].includes(j.status) },
  { key: "applied", title: "Applied", hint: "", test: j => j.status === "submitted" && (!j.outcome || j.outcome === "received") },
  { key: "talking", title: "Assessment or interview", hint: "", test: j => j.status === "submitted" && ["assessment", "interview"].includes(j.outcome ?? "") },
  { key: "offer", title: "Offer", hint: "", test: j => j.outcome === "offer" },
  { key: "rejected", title: "Rejected", hint: "", test: j => j.outcome === "rejected" },
];

export default function Tracker() {
  const { status } = useContext(StatusCtx);
  const [jobs, setJobs] = useState<Job[]>([]);
  const load = () => api.get<Resp>("/api/jobs?status=drafted,filling,filled,error,submitted&limit=500&sort=posted&include_closed=true")
    .then(r => setJobs(r.jobs)).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, []);
  const placed = new Set<string>();
  const cols = COLS.map(c => {
    const items = jobs.filter(j => !placed.has(j.id) && c.test(j, !!status?.active[j.id]));
    items.forEach(j => placed.add(j.id));
    return { ...c, items };
  });

  return (
    <div className="page wide">
      <div className="page-h">
        <div><h1>Tracker</h1></div>
      </div>
      <div className="board">
        {cols.map(c => (
          <section key={c.key} className={`col col-${c.key}`} aria-labelledby={`col-${c.key}`}>
            <h2 id={`col-${c.key}`}>{c.title}<span className="muted"> ({c.items.length})</span></h2>
            {c.hint && <p className="small muted">{c.hint}</p>}
            <ul>
              {c.items.map(j => (
                <li key={j.id}>
                  <a className="tcard" href={`#/job/${j.id}`}>
                    <div className="row tight"><Logo name={j.company} size={28} /><strong className="clamp1">{j.company}</strong></div>
                    <p className="clamp2">{j.title}</p>
                    {c.key === "review" && <p className="small warn-text clamp2">{j.status === "error" ? j.error : j.hold_reason ?? "Filled in. Submit it."}</p>}
                    {c.key === "working" && <p className="small muted"><Dots />{status?.active[j.id] === "drafting" ? "Researching" : "Applying"}</p>}
                    {(j.connections ?? 0) > 0 && <p className="small accent-text">{j.connections} you know there</p>}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
