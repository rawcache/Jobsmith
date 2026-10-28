import { useContext, useEffect, useState } from "react";
import { friendly } from "./Tracker";
import { ago, api, OUTCOME_LABEL } from "../api";
import { autopilotOn, setAutopilot, StatusCtx } from "../main";
import { Dots, Icon, Logo, poll } from "../ui";
import Ask from "../components/Ask";
import Live from "../components/Live";

type Item = { key: string; label: string; detail?: string; done: boolean; href: string; points?: number };
type HomeData = {
  applied_today: number; applied_week: number; applied_total: number; in_progress: number; queued: number;
  sent_today: number; daily_cap: number; company_cap: number; remaining_today: number; autonomy: string; auto_run: boolean; next_run: number | null;
  last_summary: string; min_fit: number; network: number; first_name: string;
  review: { id: string; company: string; title: string; status: string; hold_reason: string | null; error: string | null; updated_at: number; approve?: boolean }[];
  recent: { id: string; company: string; title: string; outcome: string | null; finished_at: number }[];
  sources: { id: number; url: string; last_synced: number | null; last_count: number | null }[];
  strength: { percent: number; items: Item[] }; started: Item[];
  stages: Record<"working" | "paused" | "needs" | "applied" | "interviewing" | "offer" | "rejected", number>;
  email: boolean; gmail: string;
};

const srcName = (u: string) => u.replace(/^https?:\/\/(www\.)?github\.com\//, "").replace(/\/$/, "");
const greeting = () => { const h = new Date().getHours(); return h < 5 ? "Hi" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };

export default function Home() {
  const { status, refresh } = useContext(StatusCtx);
  const [d, setD] = useState<HomeData | null>(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const load = () => api.get<HomeData>("/api/home").then(setD).catch(() => {});
  useEffect(() => { load(); const t = poll(load, 5000); return () => t.stop(); }, []);
  const on = autopilotOn(status);
  const runNow = async () => {
    setBusy("run");
    const r = await api.post<{ summary?: string }>("/api/auto/run-now").catch(() => ({ summary: "" }));
    setNote(r.summary ?? ""); setBusy(""); load(); refresh();
  };
  const checkMail = async () => {
    setBusy("mail");
    type R = { error?: string; checked?: number; new_outcomes?: number };
    const r: R = await api.post<R>("/api/outcomes/check").catch(e => ({ error: (e as Error).message }));
    setNote(r.error ?? `Read ${r.checked} emails: ${r.new_outcomes} new replies.`); setBusy(""); load();
  };

  if (!d) return <div className="page home"><p className="muted"><Dots />Loading</p></div>;
  const startedDone = d.started.filter(i => i.done).length;
  const prefsDone = d.started.find(i => i.key === "prefs")?.done;
  const st = d.stages;
  const STAGES: [string, number, string][] = [["Working on it", st.working + st.paused, ""], ["Needs you", st.needs, "warn"], ["Applied", st.applied, ""],
    ["Interviewing", st.interviewing, "ok"], ["Offers", st.offer, "ok"], ["Rejected", st.rejected, ""]];

  const QUICK: [string, string, string, string | (() => void)][] = [
    ["bolt", "Look for new roles", "Check your job lists now", runNow],
    ["sliders", "Job preferences", "What autopilot looks for", "#/preferences"],
    ["doc", "Resume and letters", "What employers get", "#/documents"],
    ["sparkle", "Your voice", "Answers in your own words", "#/voice"],
    ["linkedin", "Import from LinkedIn", "Your history and connections", "#/profile"],
    ["ext", "Chrome extension", "Autofill on any posting", "#/settings/extension"],
  ];

  return (
    <div className="page home">
      <section className="hero-band">
        <div className="hero-in">
          <h1>{greeting()}{d.first_name ? `, ${d.first_name}` : ""}</h1>
          <div className="hero-card">
            <div className="hero-top">
              <span className={`hero-ic ${on ? "lit" : ""}`}><Icon name="bolt" size={18} /></span>
              <div className="grow">
                <h2>{on ? "Autopilot is applying for you" : "Autopilot is off"}</h2>
                <p className="muted">{on
                  ? `${d.daily_cap > 0 ? `${d.sent_today} of ${d.daily_cap} today` : `${d.sent_today} sent today`}, ${d.applied_week} this week. ${d.remaining_today === 0 ? "Today's cap is reached; autopilot starts again tomorrow." : `${d.queued} good matches are next.`}`
                  : `${d.queued} good matches are ready. Turn it on and it applies while you're away.`}</p>
              </div>
              {on ? <button className="btn primary" onClick={runNow} disabled={!!busy}>{busy === "run" ? <Dots /> : "Apply to new matches now"}</button>
                : <button className="btn primary" onClick={() => setAutopilot(true).then(() => { refresh(); load(); })}>Turn on autopilot</button>}
            </div>
            <Ask onDone={load} />
            {note && <p className="note">{note}</p>}
            {!prefsDone && <a className="hero-cta" href="#/preferences"><Icon name="sliders" size={14} />Fill out your job preferences so autopilot knows what to look for</a>}
          </div>
        </div>
      </section>

      <div className="home-col">
        {startedDone < d.started.length && (
          <section className="card started">
            <div className="started-h">
              <div><h2>Get started with Jobsmith</h2><p className="small muted">A few steps and it can apply on its own.</p></div>
              <span className="q-bar prog"><span style={{ width: `${startedDone / d.started.length * 100}%` }} /></span>
              <span className="small accent-text num">{startedDone}/{d.started.length}</span>
            </div>
            <ul className="gs-cards">
              {d.started.map(i => (
                <li key={i.key} className={i.done ? "done" : ""}>
                  <a href={i.href}>
                    <span className="gs-ic">{i.done ? <Icon name="check" size={14} /> : <Icon name="plus" size={14} />}</span>
                    <span className="grow"><strong>{i.label}</strong>{i.detail && <span className="small muted clamp2">{i.detail}</span>}</span>
                    {!i.done && <span className="gs-go" aria-hidden>→</span>}
                  </a>
                </li>))}
            </ul>
          </section>
        )}

        <a className="metrics" href="#/tracker" aria-label="My applications">
          {STAGES.map(([l, n, tone]) => (
            <span key={l} className={`metric ${tone} ${n ? "" : "zero"}`}><b className="num">{n}</b><span>{l}</span></span>))}
        </a>

        {(status?.live ?? 0) > 0 && (
          <section className="card">
            <div className="card-h"><h2>Applying right now</h2><Overall /></div>
            <Live />
          </section>
        )}

        <section className="card flush">
          <div className="card-h"><h2>Needs you</h2>{d.review.length > 0 && <span className="badge warn">{d.review.length}</span>}
            {d.review.length > 0 && <a href="#/tracker">View all</a>}</div>
          {d.review.length === 0 ? <p className="empty">Nothing is waiting on you.</p> : (
            <ul className="lrows">{d.review.slice(0, 6).map(j => (
              <li key={j.id}><a href={`#/matches/${j.id}`}>
                <Logo name={j.company} size={28} />
                <span className="lr-main"><strong>{j.company}</strong><span className="clamp1 muted">{j.title}</span></span>
                <span className={`badge ${j.status === "error" ? "bad" : "warn"} clamp1`}>{j.status === "error" ? friendly(j.error) : j.approve ? "Approve autopilot's first submission" : (j.hold_reason ?? "Ready to submit")}</span>
                <span className="lr-when muted">{ago(j.updated_at)}</span>
              </a></li>))}</ul>)}
        </section>

        <section className="card flush">
          <div className="card-h"><h2>Recently applied</h2><a href="#/tracker">Applications</a></div>
          {d.recent.length === 0 ? <p className="empty">Nothing sent yet. Turn on autopilot or pick roles in <a href="#/matches">Matches</a>.</p> : (
            <ul className="lrows">{d.recent.slice(0, 6).map(r => (
              <li key={r.id}><a href={`#/matches/${r.id}`}>
                <Logo name={r.company} size={28} />
                <span className="lr-main"><strong>{r.company}</strong><span className="clamp1 muted">{r.title}</span></span>
                <span className={`badge ${r.outcome === "rejected" ? "" : r.outcome ? "ok" : "info"}`}>{r.outcome ? OUTCOME_LABEL[r.outcome] : "Applied"}</span>
                <span className="lr-when muted">{ago(r.finished_at)}</span>
              </a></li>))}</ul>)}
        </section>

        <div className="two">
          <section className="card">
            <span className="badge">Profile {d.strength.percent}% complete</span>
            <h2 className="mt">{d.strength.percent >= 90 ? "Your profile is strong" : "Make your profile stronger"}</h2>
            <span className="q-bar meter-ok"><span style={{ width: `${d.strength.percent}%` }} /></span>
            {d.strength.percent < 100 && <ul className="gain">{d.strength.items.filter(i => !i.done).slice(0, 3).map(i => (
              <li key={i.key}><a href={i.href}><span className="grow">{i.label}</span><span className="plus">+{i.points}%</span></a></li>))}</ul>}
          </section>
          <section className="card">
            <div className="card-h"><h2>Email and job lists</h2><a href="#/settings">Edit</a></div>
            {d.email ? <p className="small muted"><span className="ok-text">Connected.</span> Reading {d.gmail} for codes and replies.
              {" "}<button className="link" onClick={checkMail} disabled={!!busy}>{busy === "mail" ? "Reading…" : "Check now"}</button></p>
              : <p className="small"><a href="#/settings/email">Connect your email</a> <span className="muted">so emailed codes get entered for you.</span></p>}
            <ul className="srcs">{d.sources.map(s => (
              <li key={s.id}><Icon name="github" size={13} />
                <a className="grow clamp1" href={s.url} target="_blank" rel="noreferrer">{srcName(s.url)}</a>
                <span className="muted num">{s.last_synced ? s.last_count?.toLocaleString() : "…"}</span></li>))}</ul>
          </section>
        </div>

        <h2 className="sec-h">Quick menu</h2>
        <ul className="quick">
          {QUICK.map(([icon, title, sub, go]) => (
            <li key={title}>{typeof go === "string"
              ? <a href={go}><span className="q-ic"><Icon name={icon} size={16} /></span><span className="grow"><strong>{title}</strong><span className="small muted">{sub}</span></span><span className="gs-go">→</span></a>
              : <button onClick={go} disabled={!!busy}><span className="q-ic"><Icon name={icon} size={16} /></span><span className="grow"><strong>{title}</strong><span className="small muted">{busy === "run" ? "Looking…" : sub}</span></span><span className="gs-go">→</span></button>}
            </li>))}
        </ul>
      </div>
    </div>
  );
}

/** All applications in flight, as one bar: how far along they are together. */
function Overall() {
  const { status } = useContext(StatusCtx);
  const ps = Object.values(status?.progress ?? {});
  if (ps.length < 2) return null;
  const done = ps.reduce((a, p) => a + p.step, 0), all = ps.reduce((a, p) => a + p.total, 0);
  const ready = ps.filter(p => p.step >= p.total - 1).length;
  return (
    <div className="overall" title={`${ready} of ${ps.length} filled in or sent`}>
      <span className="small muted">{ready} of {ps.length} done</span>
      <span className="q-bar wide"><span style={{ width: `${Math.round(done / all * 100)}%` }} /></span>
    </div>
  );
}
