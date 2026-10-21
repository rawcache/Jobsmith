import { useContext, useEffect, useState } from "react";
import { ago, api, Answer, companyHref, Fact } from "../api";
import { StatusCtx } from "../main";
import { Dots, Icon } from "../ui";
import { FileViewer } from "./Documents";

type Doc = { id: number; kind: string; filename: string; created_at: number };
type Entry = { id: number; kind: string; title?: string; company?: string; location?: string; start?: string; end?: string; description?: string };
type Resp = {
  facts: Fact[]; answers: (Answer & { section: string })[]; documents: Doc[]; entries: Entry[];
  resume: { resume: Doc | null; resume_pdf: Doc | null; transcript: Doc | null; attached: string | null; attachment_name: string | null };
};
type Links = {
  linkedin: { url: string } | null; website: string | null;
  github: { user: string; url: string; name?: string; bio?: string; avatar?: string; public_repos?: number; error?: string; languages?: string[];
            repos?: { name: string; url: string; description: string; language: string | null; stars: number }[] } | null;
  devpost: { user: string; url: string; name?: string; bio?: string; error?: string;
             projects?: { name: string; url: string; tagline: string; winner: boolean }[] } | null;
};
type Net = { summary: { total: number; top_companies: { company: string; n: number }[] } };
type UploadRes = { facts_added: number; method: string; warnings: string[]; message?: string };

const CATS = ["experience", "project", "education", "skill", "award", "leadership", "identity", "link", "other"];
const CAT_LABEL: Record<string, string> = { experience: "Experience", project: "Projects", education: "Education", skill: "Skills",
  award: "Awards", leadership: "Leadership", identity: "About you", link: "Links", other: "Other" };
const EEO = new Set(["gender", "race", "hispanic_latino", "veteran_status", "disability_status", "pronouns", "lgbtq", "first_gen"]);

function AnswerField({ a, onSaved }: { a: Answer; onSaved: () => void }) {
  const [v, setV] = useState(a.value);
  useEffect(() => setV(a.value), [a.value]);
  const save = () => api.put(`/api/answers/${a.key}`, { value: v, confirmed: true }).then(onSaved);
  const pending = !a.confirmed && !!a.value;
  return (
    <label className={`bank ${pending ? "pending" : ""}`}>
      <span>{a.label}{pending && <em> check this</em>}</span>
      <div className="row tight">
        <input value={v} onChange={e => setV(e.target.value)} onBlur={() => v !== a.value && save()}
               placeholder={EEO.has(a.key) ? "Blank means decline to answer" : "Not set"} />
        {pending && v === a.value && <button className="btn sm ok" onClick={save}>Confirm</button>}
      </div>
    </label>
  );
}

function EntryCard({ e, onChange }: { e: Entry; onChange: () => void }) {
  const [edit, setEdit] = useState(false);
  const [d, setD] = useState(e);
  const f = (k: keyof Entry) => (ev: { target: { value: string } }) => setD({ ...d, [k]: ev.target.value });
  if (!edit) return (
    <li className="xp" onClick={() => setEdit(true)} tabIndex={0} onKeyDown={k => k.key === "Enter" && setEdit(true)}>
      <span className="xp-dot" />
      <div><strong>{e.title}</strong><p>{e.company}{e.location ? `, ${e.location}` : ""}</p>
        <p className="small muted">{e.start} to {e.end || "present"}</p></div>
    </li>
  );
  return (
    <li className="xp editing">
      <div className="grid-2 tight">
        <label className="field">Title<input value={d.title ?? ""} onChange={f("title")} /></label>
        <label className="field">Company<input value={d.company ?? ""} onChange={f("company")} /></label>
        <label className="field">Location<input value={d.location ?? ""} onChange={f("location")} /></label>
        <div className="grid-2 tight">
          <label className="field">From<input value={d.start ?? ""} onChange={f("start")} placeholder="2025-05" /></label>
          <label className="field">To<input value={d.end ?? ""} onChange={f("end")} placeholder="present" /></label>
        </div>
      </div>
      <label className="field">Description, pasted into "describe this role" boxes<textarea rows={5} value={d.description ?? ""} onChange={f("description")} /></label>
      <div className="row tight">
        <button className="btn sm primary" onClick={() => api.put(`/api/entries/${e.id}`, d).then(() => { setEdit(false); onChange(); })}>Save</button>
        <button className="btn sm ghost" onClick={() => { setD(e); setEdit(false); }}>Cancel</button>
        <button className="btn sm ghost" onClick={() => api.del(`/api/entries/${e.id}`).then(onChange)}>Remove</button>
      </div>
    </li>
  );
}

function FactRow({ f, onChange }: { f: Fact; onChange: () => void }) {
  const [edit, setEdit] = useState(false);
  const [t, setT] = useState(f.text);
  return (
    <li className="fact">
      {edit ? (
        <div className="row tight grow"><textarea className="grow" value={t} rows={2} onChange={e => setT(e.target.value)} />
          <button className="btn sm primary" onClick={() => api.put(`/api/facts/${f.id}`, { ...f, text: t }).then(() => { setEdit(false); onChange(); })}>Save</button></div>
      ) : (<>
        <p>{f.text}{f.source && ["github", "devpost"].includes(f.source) && <span className="muted"> (from {f.source})</span>}</p>
        <div className="fact-act">
          <button className="btn ghost sm" onClick={() => setEdit(true)}>Edit</button>
          <button className="btn ghost sm" onClick={() => api.del(`/api/facts/${f.id}`).then(onChange)}>Remove</button>
        </div>
      </>)}
    </li>
  );
}

function LinksCard() {
  const [l, setL] = useState<Links | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const load = (refresh = false) => api.get<Links>(`/api/links${refresh ? "?refresh=true" : ""}`).then(setL).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!l) return <section className="card side-card"><h2>Your links</h2><p className="muted small"><Dots /> Loading previews</p></section>;
  const g = l.github, d = l.devpost;
  if (editing) return <LinksEdit onDone={() => { setEditing(false); load(true); }} />;
  return (
    <section className="card side-card links">
      <div className="card-h"><h2>Your links</h2>
        <div className="row tight"><button className="btn ghost sm" onClick={() => setEditing(true)}>Edit</button>
          <button className="btn ghost sm" onClick={() => load(true)}>Refresh</button></div></div>

      <div className="link-block">
        <div className="link-h"><Icon name="linkedin" size={18} className="li" />
          {l.linkedin ? <a href={l.linkedin.url} target="_blank" rel="noreferrer">{l.linkedin.url.replace(/^https?:\/\/(www\.)?/, "")}</a> : <span className="muted">No LinkedIn yet</span>}</div>
        <p className="small muted">LinkedIn can't be read by apps, so this is a link only.</p>
      </div>

      <div className="link-block">
        <div className="link-h"><Icon name="github" size={18} />
          {g ? <a href={g.url} target="_blank" rel="noreferrer">github.com/{g.user}</a> : <span className="muted">No GitHub yet</span>}
          {g?.public_repos != null && <span className="small muted">{g.public_repos} repos</span>}</div>
        {g?.error && <p className="small warn-text">{g.error}</p>}
        {g?.languages && g.languages.length > 0 && <p className="small muted">Mostly {g.languages.join(", ")}.</p>}
        <ul className="repo-list">{g?.repos?.slice(0, 5).map(r => (
          <li key={r.name}><a href={r.url} target="_blank" rel="noreferrer"><strong>{r.name}</strong></a>
            {r.stars > 0 && <span className="small muted"> <Icon name="star" size={11} />{r.stars}</span>}
            {r.description && <p className="small muted clamp2">{r.description}</p>}</li>))}</ul>
      </div>

      <div className="link-block">
        <div className="link-h"><Icon name="devpost" size={18} />
          {d ? <a href={d.url} target="_blank" rel="noreferrer">devpost.com/{d.user}</a> : <span className="muted">No Devpost yet</span>}</div>
        {d?.error && <p className="small warn-text">{d.error}</p>}
        <ul className="repo-list">{d?.projects?.map(p => (
          <li key={p.url}><a href={p.url} target="_blank" rel="noreferrer"><strong>{p.name}</strong></a>{p.winner && <span className="muted"> (winner)</span>}
            {p.tagline && <p className="small muted clamp2">{p.tagline}</p>}</li>))}</ul>
      </div>
      {(g?.repos?.length || d?.projects?.length) ? (
        <button className="btn sm block" disabled={busy} onClick={async () => {
          setBusy(true); const r = await api.post<{ added: number }>("/api/links/facts"); setBusy(false);
          setMsg(r.added ? `Added ${r.added} project${r.added > 1 ? "s" : ""} to your facts.` : "Your projects are already in your facts.");
        }}>{busy ? <Dots /> : "Use these projects in answers"}</button>
      ) : null}
      {msg && <p className="small ok-text">{msg}</p>}
    </section>
  );
}

const LINK_KEYS: [string, string, string][] = [["linkedin", "LinkedIn", "https://www.linkedin.com/in/you"],
  ["github", "GitHub", "https://github.com/you"], ["devpost", "Devpost", "https://devpost.com/you"],
  ["website", "Website or portfolio", "https://you.dev"]];

function LinksEdit({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState<Record<string, string> | null>(null);
  useEffect(() => { api.get<{ answers: { key: string; value: string }[] }>("/api/profile")
    .then(p => setV(Object.fromEntries(LINK_KEYS.map(([k]) => [k, p.answers.find(a => a.key === k)?.value ?? ""])))); }, []);
  if (!v) return <section className="card side-card"><p className="muted small"><Dots />Loading</p></section>;
  const fix = (k: string, s: string) => {
    s = s.trim();
    if (!s || /^https?:\/\//.test(s)) return s;
    if (k === "github" && !s.includes(".")) return `https://github.com/${s.replace(/^@/, "")}`;   // just a username
    if (k === "devpost" && !s.includes(".")) return `https://devpost.com/${s}`;
    return `https://${s}`;
  };
  const save = async () => {
    for (const [k] of LINK_KEYS) await api.put(`/api/answers/${k}`, { value: fix(k, v[k] ?? ""), confirmed: true });
    onDone();
  };
  return (
    <section className="card side-card links">
      <div className="card-h"><h2>Your links</h2></div>
      {LINK_KEYS.map(([k, label, ph]) => (
        <label key={k} className="field">{label}<input value={v[k] ?? ""} placeholder={ph} onChange={e => setV({ ...v, [k]: e.target.value })} /></label>))}
      <p className="small muted">A username works too, like <code>rawcache</code> for GitHub.</p>
      <div className="row tight"><button className="btn primary sm" onClick={save}>Save</button><button className="link" onClick={onDone}>Cancel</button></div>
    </section>
  );
}

function NetworkCard({ onImported }: { onImported?: () => void }) {
  const [n, setN] = useState<Net | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => api.get<Net>("/api/connections").then(setN).catch(() => {});
  useEffect(() => { load(); }, []);
  const up = async (fl: FileList | null) => {
    if (!fl?.length) return;
    const fd = new FormData(); fd.append("file", fl[0]);
    setMsg("Reading it…");
    try { const r = await api.post<{ message: string }>("/api/linkedin", fd);
      setMsg(r.message); load(); onImported?.();
    } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <section className="card side-card">
      <div className="card-h"><h2>From LinkedIn</h2>{n && n.summary.total > 0 && <span className="muted"> ({n.summary.total.toLocaleString()} connections)</span>}</div>
      <p className="small muted">Your name, headline, work history, education, certifications, languages and skills, plus who you know at each company. LinkedIn doesn't let apps read profiles, but it gives you the file.</p>
      {n && n.summary.total > 0 ? (<>
        
        <ul className="top-cos">{n.summary.top_companies.slice(0, 8).map(c => <li key={c.company}><a href={companyHref(c.company)}>{c.company}</a><span className="muted small">{c.n}</span></li>)}</ul>
      </>) : (
        <ol className="small steps">
          <li>On LinkedIn, open <a href="https://www.linkedin.com/mypreferences/d/download-my-data" target="_blank" rel="noreferrer">Settings, Data privacy, Get a copy of your data</a>.</li>
          <li>Tick <strong>Profile</strong> and <strong>Connections</strong> (or take the whole archive) and request it. It arrives by email, usually within the hour.</li>
          <li>Upload the .zip here as it is.</li>
        </ol>
      )}
      <label className="btn sm block upload-btn"><input type="file" accept=".zip,.csv" onChange={e => { up(e.target.files); e.target.value = ""; }} />
        <Icon name="upload" size={14} />{n?.summary.total ? "Update from a newer LinkedIn file" : "Upload your LinkedIn .zip"}</label>
      {msg && <p className="small">{msg}</p>}
    </section>
  );
}

function Slot({ title, hint, accept, doc, label, onPick, busy, onView }: {
  title: string; hint: string; accept: string; doc: Doc | null; label?: string | null; onPick: (f: FileList | null) => void;
  busy: boolean; onView: (d: Doc) => void;
}) {
  return (
    <div className={`slot ${doc ? "filled" : ""}`}>
      <span className={`doc-ico ${doc?.filename.split(".").pop() ?? "none"}`}>{doc ? doc.filename.split(".").pop()?.toUpperCase() : <Icon name="plus" size={16} />}</span>
      <div className="grow">
        <strong>{title}</strong>
        {doc ? <button className="linkish" onClick={() => onView(doc)}>{label ?? doc.filename}</button> : <p className="small muted">{hint}</p>}
      </div>
      {doc && <button className="btn ghost sm" onClick={() => onView(doc)}><Icon name="eye" size={14} />View</button>}
      <label className="btn sm upload-btn"><input type="file" accept={accept} onChange={e => { onPick(e.target.files); e.target.value = ""; }} />
        {busy ? <Dots /> : doc ? "Replace" : "Upload"}</label>
    </div>
  );
}

export default function Profile() {
  const { refresh } = useContext(StatusCtx);
  const [r, setR] = useState<Resp | null>(null);
  const [msg, setMsg] = useState<string[]>([]);
  const [uploading, setUploading] = useState("");
  const [nf, setNf] = useState({ category: "project", subject: "", text: "" });
  const [viewing, setViewing] = useState<Doc | null>(null);
  const [tab, setTab] = useState<"files" | "answers" | "work" | "facts">("answers");
  const load = () => api.get<Resp>("/api/profile").then(setR);
  useEffect(() => { load(); }, []);

  const upload = async (files: FileList | null, slot: string) => {
    if (!files?.length) return;
    setUploading(slot);
    const out: string[] = [];
    for (const file of Array.from(files)) {
      const fd = new FormData(); fd.append("file", file); fd.append("slot", slot);
      try { const res = await api.post<UploadRes>("/api/profile/upload", fd);
        out.push(res.message ?? `${file.name}: read ${res.facts_added} facts.`, ...res.warnings);
      } catch (e) { out.push(`${file.name}: ${(e as Error).message}`); }
    }
    setMsg(out); setUploading(""); load(); refresh();
  };

  if (!r) return <div className="page"><p className="muted"><Dots /> Loading</p></div>;
  const a = Object.fromEntries(r.answers.map(x => [x.key, x.value]));
  const name = [a.preferred_name || a.first_name, a.last_name].filter(Boolean).join(" ") || "Your name";
  const toConfirm = r.answers.filter(x => x.value && !x.confirmed).length;
  const grouped = CATS.map(c => [c, r.facts.filter(f => f.category === c)] as const).filter(([, fs]) => fs.length);

  return (
    <div className="page">
      <div className="layout-side flip">
        <aside className="col-side">
          <section className="card side-card me">
            <span className="avatar xl">{name.split(" ").map(w => w[0]).slice(0, 2).join("")}</span>
            <h1>{name}</h1>
            <p className="muted">{[a.degree, a.major].filter(Boolean).join(" in ")}{a.school ? `, ${a.school}` : ""}</p>
            <ul className="me-facts">
              {a.graduation_date && <li><Icon name="clock" size={14} />Graduates {a.graduation_date}</li>}
              {a.location && <li><Icon name="pin" size={14} />{a.location}</li>}
              {a.email && <li><Icon name="user" size={14} />{a.email}</li>}
              {a.gpa && <li><Icon name="star" size={14} />GPA {a.gpa}</li>}
            </ul>
            
          </section>
          <LinksCard />
          <NetworkCard onImported={() => { load(); refresh(); }} />
        </aside>

        <div className="col-main">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "answers"} onClick={() => setTab("answers")}>Answers{toConfirm ? <span className="muted"> ({toConfirm})</span> : null}</button>
            <button role="tab" aria-selected={tab === "files"} onClick={() => setTab("files")}>Resume and files</button>
            <button role="tab" aria-selected={tab === "work"} onClick={() => setTab("work")}>Work history</button>
            <button role="tab" aria-selected={tab === "facts"} onClick={() => setTab("facts")}>Facts <span className="muted"> ({r.facts.length})</span></button>
          </div>
          {msg.length > 0 && <ul className="toast">{msg.map(m => <li key={m}>{m}</li>)}</ul>}

          {tab === "files" && (
            <section className="card">
              <h2>Resume and files</h2>
              <Slot title="Resume" accept=".tex,.pdf,.docx,.txt,.md" busy={uploading === "resume"} onView={setViewing} doc={r.resume.resume}
                    onPick={f => upload(f, "resume")} hint="Your LaTeX .tex is read exactly. A PDF or Word file works too." />
              <Slot title="PDF employers get" accept=".pdf" busy={uploading === "resume_pdf"} onView={setViewing} doc={r.resume.resume_pdf}
                    label={r.resume.resume_pdf && r.resume.attachment_name ? `Sent as ${r.resume.attachment_name}` : null}
                    onPick={f => upload(f, "resume_pdf")} hint="The exact file attached to every application." />
              <Slot title="Transcript" accept=".pdf" busy={uploading === "transcript"} onView={setViewing} doc={r.resume.transcript}
                    onPick={f => upload(f, "transcript")} hint="Attached only when a form requires one." />
              {r.documents.filter(d => d.kind === "extra").map(d => (
                <div key={d.id} className="slot filled">
                  <span className={`doc-ico ${d.filename.split(".").pop()}`}>{d.filename.split(".").pop()?.toUpperCase()}</span>
                  <div className="grow"><strong>Supporting file</strong><button className="linkish" onClick={() => setViewing(d)}>{d.filename}</button></div>
                  <span className="small muted">{ago(d.created_at)}</span>
                  <button className="btn ghost sm" onClick={() => api.del(`/api/documents/${d.id}`).then(() => { load(); refresh(); })}>Remove</button>
                </div>))}
              <div className="slot">
                <span className="doc-ico none"><Icon name="plus" size={16} /></span>
                <div className="grow"><strong>Anything else</strong><p className="small muted">Certificates, awards, project write-ups. Each becomes facts answers can cite.</p></div>
                <label className="btn sm upload-btn"><input type="file" multiple accept=".pdf,.docx,.txt,.md,.tex" onChange={e => { upload(e.target.files, "extra"); e.target.value = ""; }} />
                  {uploading === "extra" ? <Dots /> : "Add files"}</label>
              </div>
            </section>
          )}

          {tab === "answers" && (
            <section className="card">
              <div className="card-h"><h2>Answers</h2>
                {toConfirm > 0 && <button className="btn sm ok" onClick={() => api.post("/api/answers/confirm-all").then(() => { load(); refresh(); })}>Confirm all {toConfirm}</button>}</div>
              
              {[...new Set(r.answers.map(x => x.section))].map(sec => (
                <fieldset key={sec} className="bank-sec">
                  <legend>{sec}</legend>
                  <div className="bank-grid">{r.answers.filter(x => x.section === sec).map(x => <AnswerField key={x.key} a={x} onSaved={() => { load(); refresh(); }} />)}</div>
                </fieldset>
              ))}
            </section>
          )}

          {tab === "work" && (
            <section className="card">
              <div className="card-h"><h2>Work history</h2>
                <button className="btn sm" onClick={() => api.post("/api/entries", { kind: "experience", title: "New role", start: "", end: "" }).then(load)}><Icon name="plus" size={14} />Add a role</button></div>
              
              <ul className="xp-list">{r.entries.filter(e => e.kind === "experience").map(e => <EntryCard key={e.id} e={e} onChange={load} />)}</ul>
            </section>
          )}

          {tab === "facts" && (
            <section className="card">
              <h2>Facts</h2>
              
              {grouped.map(([c, fs]) => (
                <details key={c} className="fact-group" open={c === "experience"}>
                  <summary><strong>{CAT_LABEL[c]}</strong> <span className="muted"> ({fs.length})</span></summary>
                  {Object.entries(fs.reduce((acc, f) => { (acc[f.subject] ??= []).push(f); return acc; }, {} as Record<string, Fact[]>)).map(([subj, items]) => (
                    <div key={subj} className="subj">{subj && <h4>{subj}</h4>}
                      <ul>{items.filter(f => f.text !== subj).map(f => <FactRow key={f.id} f={f} onChange={load} />)}</ul></div>))}
                </details>
              ))}
              <details className="fact-group"><summary><strong>Add a fact</strong></summary>
                <div className="addfact">
                  <select value={nf.category} onChange={e => setNf({ ...nf, category: e.target.value })}>{CATS.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}</select>
                  <input placeholder="Role or project (optional)" value={nf.subject} onChange={e => setNf({ ...nf, subject: e.target.value })} />
                  <textarea rows={2} placeholder="e.g. Led a team of 4 building the robot's vision stack in ROS 2" value={nf.text} onChange={e => setNf({ ...nf, text: e.target.value })} />
                  <button className="btn primary sm" disabled={!nf.text.trim()} onClick={() => api.post("/api/facts", nf).then(() => { setNf({ ...nf, text: "" }); load(); })}>Add fact</button>
                </div>
              </details>
            </section>
          )}
        </div>
      </div>
      {viewing && <FileViewer v={{ title: viewing.filename, name: viewing.filename, src: `/api/documents/${viewing.id}/file` }} onClose={() => setViewing(null)} />}
    </div>
  );
}
