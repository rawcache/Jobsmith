import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Icon, poll } from "../ui";

/** Needs you, by fix: each thing held applications wait on, once, with how many it unblocks and a way to answer it
 *  right here. Answering re-checks every held application; the complete ones go out within your limits. */
export type Fix = {
  id: string; kind: "resume_pdf" | "profile" | "essay" | "question"; title: string; detail: string;
  choices?: string[]; value: string; unblocks: number; ready_after: number; jobs: string[];
  part: "you" | "job";     // asked once for every form, or one application's own question
};
export type HeldJob = { id: string; company: string; title: string; own: string[]; questions: string[] };
export type FixesData = { held: number; fixes: Fix[]; applications: HeldJob[] };
type Answered = FixesData & { freed: string[]; started: string[]; note: string };

/** onCount: how many fixes there are, each time they load (Home says "Nothing is waiting" only at none). */
export default function Fixes({ onChange, onCount, limit = 6 }: { onChange?: () => void; onCount?: (n: number) => void; limit?: number }) {
  const [d, setD] = useState<FixesData | null>(null);
  const [said, setSaid] = useState("");
  // what you've typed, by fix: kept here, so a refresh that moves or hides a row never loses it
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const seq = useRef(0);       // only the newest answer is shown: a refresh sent before your answer landed is dropped
  const show = (r: FixesData) => { setD(r); onCount?.(r.fixes.length); };
  // kept fresh while you look: autopilot holds new applications as it works
  useEffect(() => {
    const get = () => {
      const mine = ++seq.current;
      api.get<FixesData>("/api/fixes").then(r => { if (mine === seq.current) show(r); }).catch(() => {});
    };
    get(); const t = poll(get, 15000); return () => t.stop();
  }, []);
  if (!d || d.fixes.length === 0) return null;
  const done = (r: Answered) => {
    seq.current++;
    show(r);
    const n = r.freed.length, s = r.started.length;
    setSaid(r.note || (n === 0 ? "Saved. Nothing else was waiting on just that." :
      `Saved. ${n} application${n === 1 ? " has" : "s have"} nothing left${s ? `: ${s} going out now` : ""}.`));
    onChange?.();
  };
  // Two parts. About you: asked once, used on every form. About one job: what only that application asks, under
  // its company and role, with a way to skip the job instead.
  const you = d.fixes.filter(f => f.part !== "job");
  const byId = Object.fromEntries(d.fixes.map(f => [f.id, f]));
  const jobs = d.applications.filter(a => a.questions.length > 0);
  // the first few, and any you've started typing in wherever a refresh put it
  const shownYou = you.filter((f, i) => i < limit || (drafts[f.id] ?? "") !== "");
  const shownJobs = jobs.filter((a, i) => i < limit || a.questions.some(q => (drafts[q] ?? "") !== ""));
  const more = (you.length - shownYou.length) + (jobs.length - shownJobs.length);
  const row = (f: Fix) => <FixRow key={f.id} f={f} onDone={done} v={drafts[f.id] ?? f.value ?? ""}
    setV={t => setDrafts(x => ({ ...x, [f.id]: t }))} clear={sent => setDrafts(x => {
      if (x[f.id] !== sent) return x;           // typed on while it was saving: kept
      const { [f.id]: _, ...rest } = x; return rest;
    })} />;
  const skip = async (a: HeldJob) => {
    try {
      seq.current++;
      show(await api.post<FixesData>("/api/fixes/skip", { job_id: a.id }));
      setSaid(`Skipped ${a.company} · ${a.title}. Nothing was sent.`);
      onChange?.();
    } catch (e) { setSaid((e as Error).message); }
  };
  return (
    <div className="fixes">
      {said && <p className="small ok-text fix-said" role="status">{said}</p>}
      {shownYou.length > 0 && (<section aria-label="About you">
        <h3 className="fix-part">About you <span className="muted">· answer once, used on every form</span></h3>
        <ul className="fix-rows">{shownYou.map(row)}</ul>
      </section>)}
      {shownJobs.length > 0 && (<section aria-label="About one job">
        <h3 className="fix-part">About one job <span className="muted">· asked by that application only, never reused</span></h3>
        {shownJobs.map(a => (
          <div key={a.id} className="fix-job">
            <div className="fix-h"><a href={`#/job/${a.id}`}><strong>{a.company}</strong> · {a.title}</a>
              <button className="link small" onClick={() => skip(a)}>Skip this job</button></div>
            <ul className="fix-rows">{a.questions.map(q => byId[q]).filter(Boolean).map(row)}</ul>
            {a.own.length > 0 && <p className="small muted">Also on this one: {a.own.slice(0, 2).join("; ").slice(0, 220)}</p>}
          </div>))}
      </section>)}
      {more > 0 && <p className="small muted">{more} more in <a href="#/tracker">Applications</a>.</p>}
    </div>
  );
}

function FixRow({ f, onDone, v, setV, clear }: { f: Fix; onDone: (r: Answered) => void; v: string; setV: (t: string) => void;
                                                clear: (sent: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const send = async (value: string) => {
    setBusy(true); setErr("");
    try { onDone(await api.post<Answered>("/api/fixes/answer", { id: f.id, value })); clear(value); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setErr("");
    const fd = new FormData(); fd.append("file", files[0]); fd.append("slot", "resume_pdf");
    try { await api.post("/api/profile/upload", fd); onDone(await api.post<Answered>("/api/fixes/answer", { id: f.id })); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const count = f.kind === "resume_pdf" ? "blocks every application" : f.part === "job" ? "" : `unblocks ${f.unblocks}`;
  return (
    <li className="fix">
      <div className="fix-h"><strong>{f.title}</strong>{count && <span className="badge warn num">{count}</span>}</div>
      <p className="small muted">{f.part === "job" ? "Your answer goes on this application only." : f.detail}{f.part !== "job" && f.ready_after > 0 && f.kind !== "resume_pdf" && f.ready_after < f.unblocks
        ? ` ${f.ready_after} need nothing else.` : ""}</p>
      {f.kind === "resume_pdf" ? (
        <label className="btn sm primary upload-btn"><input type="file" accept=".pdf" disabled={busy}
          onChange={e => { upload(e.target.files); e.target.value = ""; }} /><Icon name="upload" size={14} />Upload your resume PDF</label>
      ) : f.choices && f.choices.length > 0 ? (
        <div className="fix-choices">{f.choices.map(c => (
          <button key={c} className="btn sm" disabled={busy} onClick={() => send(c)}>{c}</button>))}</div>
      ) : f.kind === "essay" ? (
        <form onSubmit={e => { e.preventDefault(); send(v); }}>
          <textarea rows={4} value={v} onChange={e => setV(e.target.value)} aria-label={f.title}
            placeholder="Your answer, in your words. {company} and {role} are filled in for each application." />
          <button className="btn sm primary" disabled={busy || !v.trim()}>Save your answer</button>
        </form>
      ) : (
        <form className="fix-line" onSubmit={e => { e.preventDefault(); send(v); }}>
          <input value={v} onChange={e => setV(e.target.value)} aria-label={f.title} placeholder="Your answer" />
          <button className="btn sm primary" disabled={busy || !v.trim()}>Save</button>
        </form>
      )}
      {err && <p className="small bad-text">{err}</p>}
    </li>
  );
}
