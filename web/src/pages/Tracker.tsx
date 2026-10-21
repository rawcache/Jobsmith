import { useContext, useEffect, useState } from "react";
import { ago, api, Job } from "../api";
import { Status, StatusCtx } from "../main";
import { Dots, Icon, Logo, poll, Steps } from "../ui";

type Resp = { jobs: Job[] };
const COLS: { key: string; title: string; test: (j: Job, busy: boolean) => boolean }[] = [
  { key: "working", title: "Working on it", test: (_j, b) => b },
  { key: "waiting", title: "Paused", test: j => ["drafted", "filling", "new", "fetched"].includes(j.status) },
  { key: "review", title: "Needs you", test: j => ["filled", "error"].includes(j.status) },
  { key: "applied", title: "Applied", test: j => j.status === "submitted" && (!j.outcome || j.outcome === "received") },
  { key: "talking", title: "Interviewing", test: j => j.status === "submitted" && ["assessment", "interview"].includes(j.outcome ?? "") },
  { key: "offer", title: "Offer", test: j => j.outcome === "offer" },
  { key: "rejected", title: "Rejected", test: j => j.outcome === "rejected" },
];

/** Why a paused application isn't moving, in a few words. */
function pausedWhy(j: Job, quota: Status["quota"]): string {
  if (j.hold_reason === "Stopped by you") return "Stopped when you turned autopilot off.";
  if (j.ai_blocked || /AI|quota|limit/i.test(j.error ?? "")) {
    if (quota?.limited) return `Waiting for ${quota.name}'s free limit to reset (${new Date(quota.resets_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}).`;
    return "Waiting for an AI to write its answers.";
  }
  return "Drafted, waiting to be filled.";
}

/** "Needs you" reasons, kind first: the one thing to do. */
function needsWhy(j: Job): { kind: string; text: string } {
  if (j.status === "error") return { kind: "Couldn't finish", text: friendly(j.error) };
  const h = j.hold_reason ?? "";
  if (!h) return { kind: "Ready to submit", text: "Filled in. Check it and submit." };
  const n = h.split("; ").length;
  if (/emailed|code/i.test(h)) return { kind: "Code needed", text: "Enter the code they emailed you." };
  if (/required and empty|couldn't fill|no answer/i.test(h)) return { kind: `${n} to fill`, text: h.split("; ").map(x => x.split(":")[0]).slice(0, 3).join(", ") };
  if (/AI wasn't sure|not yet trusted/i.test(h)) return { kind: `${n} to check`, text: h.split("; ").map(x => x.split(":")[0]).slice(0, 3).join(", ") };
  return { kind: "Check it", text: h };
}

/** Raw errors from the network or a site, said plainly. */
export function friendly(e?: string | null): string {
  if (!e) return "Something went wrong. Open it to try again.";
  if (/404|not found/i.test(e)) return "The posting is gone (the company may have closed it).";
  if (/nodename|name or service|getaddrinfo|ENOTFOUND|resolve/i.test(e)) return "Couldn't reach the site. Check your internet, then try again.";
  if (/timeout|timed out/i.test(e)) return "The site was too slow to respond. Try again.";
  if (/403|forbidden|captcha|blocked/i.test(e)) return "The site blocked automated access. Open it and apply yourself.";
  return e.length > 140 ? e.slice(0, 140) + "…" : e;
}

type Col = (typeof COLS)[number] & { items: Job[] };
const pref = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };

/** Every application, as a dense table (sortable, filterable) or as the board. */
export default function Tracker() {
  const { status } = useContext(StatusCtx);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [view, setView] = useState(() => pref("js-apps-view", "table"));
  const [q, setQ] = useState("");
  const [only, setOnly] = useState("");
  const [sort, setSort] = useState<{ k: string; dir: 1 | -1 }>({ k: "updated", dir: -1 });
  const load = () => api.get<Resp>("/api/jobs?status=drafted,filling,filled,error,submitted&limit=500&sort=posted&include_closed=true")
    .then(r => setJobs(r.jobs)).catch(() => {});
  useEffect(() => { load(); const t = poll(load, 6000); return () => t.stop(); }, []);
  useEffect(() => { try { localStorage.setItem("js-apps-view", view); } catch { /* fine */ } }, [view]);
  const placed = new Set<string>();
  const stageOf: Record<string, string> = {};
  const cols: Col[] = COLS.map(c => {
    const items = jobs.filter(j => !placed.has(j.id) && c.test(j, !!status?.active[j.id]));
    items.forEach(j => { placed.add(j.id); stageOf[j.id] = c.key; });
    return { ...c, items };
  });
  const waiting = cols.find(c => c.key === "waiting")!.items;

  return (
    <div className="page wide">
      <div className="page-h">
        <div><h1>Applications</h1><p className="muted">{jobs.length} so far, from started to offer.</p></div>
        {waiting.length > 0 && <button className="btn sm" onClick={() => api.post("/api/jobs/batch", { action: "autopilot", ids: waiting.map(j => j.id) })}>
          Resume the {waiting.length} paused</button>}
      </div>
      <div className="toolbar">
        <label className="search"><Icon name="search" size={14} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Company or role" aria-label="Search applications" /></label>
        <select className="filter" value={only} onChange={e => setOnly(e.target.value)} aria-label="Status">
          <option value="">Every status</option>{COLS.map(c => <option key={c.key} value={c.key}>{c.title} ({cols.find(x => x.key === c.key)!.items.length})</option>)}
        </select>
        <span className="grow" />
        <div className="seg icons" role="radiogroup" aria-label="View">
          <button role="radio" aria-checked={view === "table"} className={view === "table" ? "on" : ""} onClick={() => setView("table")}><Icon name="table" size={14} />Table</button>
          <button role="radio" aria-checked={view === "board"} className={view === "board" ? "on" : ""} onClick={() => setView("board")}><Icon name="board" size={14} />Board</button>
        </div>
      </div>
      {view === "table" ? <Table jobs={jobs.filter(j => (!only || stageOf[j.id] === only) && (!q || `${j.company} ${j.title}`.toLowerCase().includes(q.toLowerCase())))}
        stageOf={stageOf} sort={sort} setSort={setSort} />
        : <Board cols={cols.map(c => ({ ...c, items: c.items.filter(j => !q || `${j.company} ${j.title}`.toLowerCase().includes(q.toLowerCase())) }))} />}
    </div>
  );
}

const STAGE_LABEL: Record<string, string> = Object.fromEntries(COLS.map(c => [c.key, c.title]));
const PILL: Record<string, string> = { working: "st-working", waiting: "st-paused", review: "st-needs", applied: "st-applied", talking: "st-talking", offer: "st-offer", rejected: "st-rejected" };

function Table({ jobs, stageOf, sort, setSort }: { jobs: Job[]; stageOf: Record<string, string>;
  sort: { k: string; dir: 1 | -1 }; setSort: (s: { k: string; dir: 1 | -1 }) => void }) {
  const { status } = useContext(StatusCtx);
  const next = (j: Job) => {
    const st = stageOf[j.id];
    if (st === "working") return status?.progress?.[j.id]?.label ?? "Starting";
    if (st === "waiting") return pausedWhy(j, status?.quota ?? null);
    if (st === "review") { const w = needsWhy(j); return `${w.kind}: ${w.text}`; }
    if (st === "talking") return j.outcome === "assessment" ? "Do the assessment" : "Prepare for the interview";
    if (st === "offer") return "Decide on the offer";
    if (st === "applied") return "Waiting to hear back";
    return "";
  };
  const key = (j: Job): string | number => ({ company: j.company.toLowerCase(), role: j.title.toLowerCase(), status: COLS.findIndex(c => c.key === stageOf[j.id]),
    updated: (j as Job & { updated_at?: number }).updated_at ?? j.date_posted ?? 0, fit: j.fit_score ?? 0 } as Record<string, string | number>)[sort.k];
  const rows = [...jobs].sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * sort.dir);
  const th = (k: string, label: string) => (
    <th aria-sort={sort.k === k ? (sort.dir > 0 ? "ascending" : "descending") : undefined}>
      <button onClick={() => setSort({ k, dir: sort.k === k ? (-sort.dir as 1 | -1) : (k === "updated" || k === "fit" ? -1 : 1) })}>
        {label}{sort.k === k ? (sort.dir > 0 ? " ↑" : " ↓") : ""}</button></th>);
  if (!rows.length) return <p className="empty card">Nothing here yet. Applications appear as soon as autopilot starts one.</p>;
  return (
    <div className="table-card">
      <table className="dtable">
        <thead><tr>{th("company", "Company")}{th("role", "Role")}{th("status", "Status")}<th>Next step</th><th>Location</th>{th("updated", "Updated")}{th("fit", "Fit")}</tr></thead>
        <tbody>{rows.map(j => (
          <tr key={j.id} onClick={() => { location.hash = `#/job/${j.id}`; }}>
            <td><span className="cell-co"><Logo name={j.company} size={20} />{j.company}</span></td>
            <td className="clamp1" title={j.title}>{j.title}</td>
            <td><span className={`pill ${PILL[stageOf[j.id]] ?? ""}`}>{STAGE_LABEL[stageOf[j.id]] ?? j.status}</span></td>
            <td className="clamp1 muted" title={next(j)}>{next(j)}</td>
            <td className="clamp1 muted">{j.locations[0] ?? ""}</td>
            <td className="num muted nowrap">{ago((j as Job & { updated_at?: number }).updated_at ?? j.date_posted ?? 0)}</td>
            <td className="num">{j.fit_score != null ? Math.round(j.fit_score) : ""}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

function Board({ cols }: { cols: Col[] }) {
  const { status } = useContext(StatusCtx);
  return (
      <div className="board">
        {cols.filter(c => c.key !== "waiting" || c.items.length > 0).map(c => (
          <section key={c.key} className={`col col-${c.key}`} aria-labelledby={`col-${c.key}`}>
            <h2 id={`col-${c.key}`}>{c.title}<span className="muted"> ({c.items.length})</span></h2>
            <ul>
              {c.items.map(j => (
                <li key={j.id}>
                  <a className={`tcard tc-${c.key}`} href={`#/job/${j.id}`}>
                    <div className="row tight"><Logo name={j.company} size={26} /><strong className="clamp1">{j.company}</strong></div>
                    <p className="clamp2 tc-title">{j.title}</p>
                    {c.key === "working" && (status?.progress?.[j.id] ? <Steps p={status.progress[j.id]} /> : <p className="small muted"><Dots />Starting</p>)}
                    {c.key === "waiting" && <p className="small muted clamp2">{pausedWhy(j, status?.quota ?? null)}</p>}
                    {c.key === "review" && (() => { const w = needsWhy(j); return (<>
                      <span className={`tag ${j.status === "error" ? "tag-bad" : "tag-warn"}`}>{w.kind}</span>
                      <p className="small muted clamp2">{w.text}</p></>); })()}
                    {(j.connections ?? 0) > 0 && <p className="small accent-text">{j.connections} you know there</p>}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
  );
}
