import { useEffect, useState } from "react";
import { ago, api } from "../api";
import { Icon, Logo, Modal } from "../ui";

type Upload = { id: number; kind: string; filename: string; created_at: number };
type Gen = { job_id: string; company: string; title: string; status: string; at: number;
  files: { name: string; kind: string; path: string; size: number }[] };
type Lib = { uploads: Upload[]; per_job: Gen[] };
type Viewing = { title: string; src: string; name: string };

const KIND: Record<string, string> = { resume: "Resume source", resume_pdf: "Resume PDF employers get", transcript: "Transcript",
  extra: "Supporting file", linkedin: "LinkedIn export" };

export function FileViewer({ v, onClose }: { v: Viewing; onClose: () => void }) {
  const isPdf = /\.pdf$/i.test(v.name), isImg = /\.(png|jpe?g)$/i.test(v.name);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    if (!isPdf && !isImg) fetch(v.src).then(r => r.ok ? r.text() : Promise.reject(r.statusText)).then(t => {
      try { setText(JSON.stringify(JSON.parse(t), null, 2)); } catch { setText(t); }
    }).catch(e => setText(`Couldn't open it: ${e}`));
  }, [v.src]);
  return (
    <Modal wide onClose={onClose} title={<span className="row tight"><Icon name="doc" /><strong>{v.title}</strong>
      <a className="small" href={v.src} target="_blank" rel="noreferrer">Open in a new tab</a></span>}>
      {isPdf ? <iframe className="doc-frame" src={v.src} title={v.name} /> : isImg ? <img className="peek-img" src={v.src} alt={v.name} />
        : <pre className="doc-text">{text ?? "Loading…"}</pre>}
    </Modal>
  );
}

export default function Documents() {
  const [lib, setLib] = useState<Lib | null>(null);
  const [v, setV] = useState<Viewing | null>(null);
  useEffect(() => { api.get<Lib>("/api/library").then(setLib); }, []);
  const latest = (k: string) => lib?.uploads.find(u => u.kind === k);
  const core = ["resume", "resume_pdf", "transcript"].map(k => latest(k)).filter(Boolean) as Upload[];
  const extras = lib?.uploads.filter(u => u.kind === "extra") ?? [];

  return (
    <div className="page">
      <div className="page-h"><div><h1>Documents</h1></div>
        <a className="btn" href="#/profile"><Icon name="upload" size={15} />Upload in Profile</a></div>

      <section className="card">
        <h2>Your files</h2>
        {lib && core.length + extras.length === 0 && <p className="muted">Nothing uploaded yet. Add your resume in Profile.</p>}
        <ul className="doc-grid">
          {[...core, ...extras].map(u => (
            <li key={u.id}><button className="doc-tile" onClick={() => setV({ title: u.filename, name: u.filename, src: `/api/documents/${u.id}/file` })}>
              <span className={`doc-ico ${u.filename.split(".").pop()}`}>{u.filename.split(".").pop()?.toUpperCase()}</span>
              <strong className="clamp1">{u.filename}</strong>
              <span className="small muted">{KIND[u.kind] ?? u.kind}, {ago(u.created_at)}</span>
            </button></li>))}
        </ul>
      </section>

      <section className="card">
        <h2>Sent with each application</h2>
        
        {lib && lib.per_job.length === 0 && <p className="muted empty-line">Nothing yet. Each application autopilot fills shows up here.</p>}
        <ul className="rows">
          {lib?.per_job.map(g => (
            <li key={g.job_id + g.at} className="gen">
              <Logo name={g.company || "?"} size={36} />
              <div className="grow">
                <a href={`#/job/${g.job_id}`}><strong>{g.company}</strong> <span className="muted">{g.title}</span></a>
                <p className="small">{g.files.map((f, k) => (<span key={f.path}>
                  <button className="link" onClick={() => setV({ title: `${g.company}: ${f.kind}`, name: f.name, src: `/api/files/${f.path}` })}>{f.kind}</button>
                  {k < g.files.length - 1 ? ", " : ""}</span>))}</p>
              </div>
              <span className="small muted">{ago(g.at)}</span>
            </li>))}
        </ul>
      </section>
      {v && <FileViewer v={v} onClose={() => setV(null)} />}
    </div>
  );
}
