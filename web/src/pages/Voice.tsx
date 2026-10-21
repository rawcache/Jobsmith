import { useEffect, useState } from "react";
import { api } from "../api";
import { Dots, Icon } from "../ui";

type Summary = {
  style: { samples: number; words?: number; avg_sentence?: number; contractions_per_100?: number; never_uses?: string[] };
  coverage: { key: string; label: string; passages: number; have: boolean }[];
  samples: { id: number; source: string; title: string; preview: string; chars: number }[];
  answers: number;
};
type Composed = { answer: string; confidence: number; rationale: string; issues: string[] } | null;

/** Your voice: the writing Jobsmith learns from, what it can answer without an AI, and which stories are missing. */
export default function Voice() {
  const [s, setS] = useState<Summary | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [q, setQ] = useState("Why do you want to work here?");
  const [tried, setTried] = useState<Composed | undefined>(undefined);
  const load = () => api.get<Summary>("/api/voice").then(setS);
  useEffect(() => { load(); }, []);
  const add = async () => {
    setBusy("add");
    const r = await api.post<Summary & { added: number }>("/api/voice", { text, title: "" });
    setS(r); setText(""); setMsg(r.added ? `Added ${r.added} passage${r.added === 1 ? "" : "s"}.` : "Nothing new to add (too short, or already here)."); setBusy("");
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy("up");
    let n = 0;
    for (const f of Array.from(files)) {
      const fd = new FormData(); fd.append("file", f);
      try { const r = await api.post<Summary & { added: number }>("/api/voice/upload", fd); n += r.added; setS(r); } catch (e) { setMsg((e as Error).message); }
    }
    setMsg(`Added ${n} passages.`); setBusy("");
  };
  const tryIt = async () => { setBusy("try"); const r = await api.post<{ answer: Composed }>("/api/voice/try", { question: q }); setTried(r.answer); setBusy(""); };
  if (!s) return <div className="page"><p className="muted"><Dots />Loading</p></div>;
  const st = s.style;
  const have = s.coverage.filter(c => c.have).length;

  return (
    <div className="page narrow">
      <div className="page-h"><div><h1>Your voice</h1>
        <p className="muted">The more of your own writing Jobsmith has, the more it sounds like you, and the less it needs an AI at all.</p></div></div>

      <div className="stages compact">
        <span className="stage"><b>{st.samples}</b>passages</span>
        <span className="stage"><b>{s.answers}</b>answers you approved</span>
        <span className="stage"><b>{st.avg_sentence ?? "–"}</b>words per sentence</span>
        <span className="stage"><b>{have}/{s.coverage.length}</b>stories covered</span>
        <span className="stage"><b>{st.never_uses?.length ?? 0}</b>phrases it won't use</span>
      </div>

      <section className="card">
        <h2>Add your writing</h2>
        <p className="small muted">Essays, cover letters, answers you wrote yourself, a personal statement. It stays on this computer.</p>
        <textarea rows={6} value={text} onChange={e => setText(e.target.value)} placeholder="Paste something you wrote" />
        <div className="row tight">
          <button className="btn primary sm" disabled={text.trim().split(/\s+/).length < 12 || !!busy} onClick={add}>{busy === "add" ? <Dots /> : "Add it"}</button>
          <label className="btn sm upload-btn"><Icon name="upload" size={14} />Add files (.md, .txt, .docx, .pdf)
            <input type="file" multiple accept=".md,.txt,.docx,.pdf" onChange={e => { upload(e.target.files); e.target.value = ""; }} /></label>
          {msg && <span className="small muted">{msg}</span>}
        </div>
      </section>

      <section className="card">
        <h2>Stories applications ask for</h2>
        <p className="small muted">A paragraph for each missing one means Jobsmith can answer it in your words, with or without an AI.</p>
        <ul className="story-list">{s.coverage.map(c => (
          <li key={c.key} className={c.have ? "have" : ""}><span className="ck" aria-hidden>{c.have ? "✓" : ""}</span>
            <span className="grow">{c.label}</span><span className="small muted mono">{c.passages || "missing"}</span></li>))}</ul>
      </section>

      <section className="card">
        <h2>Try it without an AI</h2>
        <div className="row tight"><input className="grow" value={q} onChange={e => setQ(e.target.value)} aria-label="A question" />
          <button className="btn sm" onClick={tryIt} disabled={!!busy}>{busy === "try" ? <Dots /> : "Answer it"}</button></div>
        {tried === null && <p className="small muted">Nothing you've written fits that yet. Add a paragraph about it above.</p>}
        {tried && <div className="letter"><p>{tried.answer}</p>
          <p className="small muted">{tried.rationale}. {Math.round(tried.confidence * 100)}% fit.{tried.issues.length ? ` ${tried.issues.join(" ")}` : ""}</p></div>}
      </section>

      {s.samples.length > 0 && (
        <section className="card flush">
          <div className="card-h"><h2>What it has</h2></div>
          <ul className="lrows voice-rows">{s.samples.map(p => (
            <li key={p.id}><div className="voice-row"><span className="grow small">{p.preview}{p.chars > 240 ? "…" : ""}</span>
              <span className="small muted">{p.source}</span>
              <button className="btn ghost sm" onClick={() => api.del<Summary>(`/api/voice/${p.id}`).then(setS)}>Remove</button></div></li>))}</ul>
        </section>)}
    </div>
  );
}
