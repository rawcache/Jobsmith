import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Icon, poll } from "../ui";

/** Needs you, by fix: each thing held applications wait on, once, with how many it unblocks and a way to answer it
 *  right here. Answering re-checks every held application; the complete ones go out within your limits. */
export type Fix = {
  id: string; kind: "resume_pdf" | "profile" | "essay" | "question"; title: string; detail: string;
  choices?: string[]; value: string; unblocks: number; ready_after: number; jobs: string[];
};
export type FixesData = { held: number; fixes: Fix[]; applications: { id: string; company: string; title: string; own: string[] }[] };
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
  // the first few, and any you've started typing in wherever a refresh put it
  const shown = d.fixes.filter((f, i) => i < limit || (drafts[f.id] ?? "") !== "");
  return (
    <div className="fixes">
      {said && <p className="small ok-text fix-said" role="status">{said}</p>}
      <ul className="fix-rows">{shown.map(f => <FixRow key={f.id} f={f} onDone={done} v={drafts[f.id] ?? f.value ?? ""}
        setV={t => setDrafts(x => ({ ...x, [f.id]: t }))} />)}</ul>
      {d.fixes.length > shown.length && <p className="small muted">{d.fixes.length - shown.length} more in <a href="#/tracker">Applications</a>.</p>}
    </div>
  );
}

function FixRow({ f, onDone, v, setV }: { f: Fix; onDone: (r: Answered) => void; v: string; setV: (t: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const send = async (value: string) => {
    setBusy(true); setErr("");
    try { onDone(await api.post<Answered>("/api/fixes/answer", { id: f.id, value })); setV(""); }
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
  const count = f.kind === "resume_pdf" ? "blocks every application" : `unblocks ${f.unblocks}`;
  return (
    <li className="fix">
      <div className="fix-h"><strong>{f.title}</strong><span className="badge warn num">{count}</span></div>
      <p className="small muted">{f.detail}{f.ready_after > 0 && f.kind !== "resume_pdf" && f.ready_after < f.unblocks
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
