import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { setAutopilot, StatusCtx } from "../main";
import ConnectClaude from "../components/ConnectClaude";
import Smith from "../components/Smith";
import EmailCard from "../components/EmailCard";
import { Icon, Switch } from "../ui";


type S = Record<string, any>;
type Source = { id: number; url: string; active: number; last_synced: number | null; last_count: number | null };

export default function Settings({ focus }: { focus?: string }) {
  const { refresh, status } = useContext(StatusCtx);
  const [s, setS] = useState<S | null>(null);
  const [src, setSrc] = useState<Source[]>([]);
  const [newSrc, setNewSrc] = useState("");
  const [saved, setSaved] = useState("");
  const load = () => { api.get<S>("/api/settings").then(setS); api.get<Source[]>("/api/sources").then(setSrc); };
  const [adding, setAdding] = useState(false);
  const addSource = async () => {
    const v = newSrc.trim();
    setAdding(true);
    try {
      if (/github\.com\/[^/]+\/[^/]+/.test(v)) {
        await api.post("/api/sources", { url: v }); setSaved("List added. Checking it now.");
      } else {
        const r = await api.post<{ log: string[] }>("/api/command", { text: /^https?:/.test(v) ? v : `find roles at ${v}` });
        setSaved(r.log.slice(-1)[0] ?? "Added.");
      }
      setNewSrc(""); load(); refresh();
    } catch (e) { setSaved((e as Error).message); }
    setAdding(false);
  };
  useEffect(load, []);
  useEffect(() => {
    if (!s || !focus) return;
    const el = document.getElementById(focus);
    el?.scrollIntoView({ block: "start" }); el?.classList.add("flash"); setTimeout(() => el?.classList.remove("flash"), 1600);
  }, [focus, !!s]);
  if (!s) return <div className="page"><p className="muted">Loading…</p></div>;

  const save = async (patch: S) => {
    const next = await api.put<S>("/api/settings", patch);
    setS(next); setSaved("Saved"); refresh(); setTimeout(() => setSaved(""), 1500);
  };
  const list = (k: string) => (e: { target: { value: string } }) =>
    save({ [k]: e.target.value.split(",").map(x => x.trim()).filter(Boolean) });
  const num = (k: string) => (e: { target: { value: string } }) => save({ [k]: Number(e.target.value) });

  const seg = (k: string, opts: [any, string][], cur: any) => (
    <div className="seg" role="radiogroup">{opts.map(([v, label]) => (
      <button key={String(v)} role="radio" aria-checked={cur === v} className={cur === v ? "on" : ""} onClick={() => save({ [k]: v })}>{label}</button>))}</div>
  );
  const picky = s.min_fit_score >= 55 ? 60 : s.min_fit_score <= 25 ? 20 : 40;
  const careful = s.autopilot_min_confidence >= 0.78 ? 0.8 : s.autopilot_min_confidence <= 0.55 ? 0.5 : 0.7;
  const every = s.auto_interval_hours <= 3 ? 2 : s.auto_interval_hours >= 20 ? 24 : 6;
  return (
    <div className="page narrow settings">
      <div className="page-h"><div><h1>Settings</h1><p className="muted">{saved || "Changes save as you make them."}</p></div></div>

      <section className="card">
        <h2>Applying</h2>
        <div className="set-row"><div><strong>Autopilot</strong><p>Applies on its own and holds anything it isn't sure about for you. Off means it fills forms and you press Submit.</p></div>
          <Switch on={s.autonomy !== "copilot" && s.auto_run} label="Autopilot"
            onChange={v => setAutopilot(v).then(m => { setSaved(m); load(); refresh(); })} /></div>
        <div className="set-row"><div><strong>How picky</strong><p>Which matches autopilot applies to.</p></div>
          {seg("min_fit_score", [[60, "Strong fits"], [40, "Good fits"], [20, "Anything I qualify for"]], picky)}</div>
        <div className="set-row"><div><strong>Limits</strong><p>Autopilot stops at these and says which one. You can still submit yourself. Blank means no limit.</p></div>
          <div className="grid-2 tight caps">
            <label className="field">Most a day<input type="number" min={0} placeholder="No limit" value={s.max_applications_per_day || ""} onChange={num("max_applications_per_day")} /></label>
            <label className="field">Per company each week<input type="number" min={0} placeholder="No limit" value={s.max_applications_per_company || ""} onChange={num("max_applications_per_company")} /></label>
          </div></div>
        <div className="set-row"><div><strong>Applications at once</strong><p>More is faster; each one opens its own tab.</p></div>
          {seg("concurrency", [[1, "1"], [3, "3"], [5, "5"]], [1, 3, 5].includes(s.concurrency) ? s.concurrency : 3)}</div>
        <div className="set-row"><div><strong>Check for new roles</strong><p>While Jobsmith is open and your computer is awake.</p></div>
          {seg("auto_interval_hours", [[2, "Every 2 hours"], [6, "Every 6 hours"], [24, "Daily"]], every)}</div>
        <div className="set-row"><div><strong>When an answer is unsure</strong><p>How readily autopilot holds an application for you to check.</p></div>
          {seg("autopilot_min_confidence", [[0.8, "Hold more"], [0.7, "Balanced"], [0.5, "Hold less"]], careful)}</div>
        <div className="row"><button className="btn" onClick={() => api.post<{ summary: string }>("/api/auto/run-now").then(r => { setSaved(r.summary); refresh(); })}>Look for new roles now</button>
          {status?.auto.last_summary && <span className="small muted">{status.auto.last_summary}</span>}</div>
        <p className="small muted">You're responsible for what's sent in your name. CAPTCHAs, sign-ins and emailed codes always come to you.</p>
      </section>

      <a className="card link-card" href="#/preferences">
        <div className="grow"><h2>Job preferences</h2><p className="small muted">What, where, and how picky. They have their own page now.</p></div>
        <Icon name="back" size={16} className="chev" />
      </a>

      <EmailCard s={s} save={save} onMsg={setSaved} />

      <section className="card">
        <h2>Your AI</h2>
        <p>{status ? <>Writing with <strong>{status.llm.writing.label}</strong>{status.llm.writing.ok ? "." : <span className="warn-text">: {status.llm.writing.message}</span>}</> : null}</p>
        <div className="ai-pick">
          {([["gemini_api", "Gemini", "Free. Writes well and researches companies."], ["ollama", "smith", "Free and private, on this computer."],
             ["anthropic_api", "Claude", "API key, pay per use."], ["openai_api", "ChatGPT", "API key, pay per use."]] as [string, string, string][]).map(([k, label, hint]) => (
            <label key={k} className={`choice ${s.llm_backend === k ? "on" : ""}`}>
              <input type="radio" name="ai" checked={s.llm_backend === k} onChange={() => save({ llm_backend: k, research_backend: "same" })} />
              <div><strong>{label}</strong><p>{hint}</p></div></label>))}
        </div>
        {s.llm_backend === "gemini_api" && <label className="field">Gemini key <a className="small" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">get one</a>
          <input type="password" defaultValue={s.gemini_api_key} placeholder="Paste your key" onBlur={e => save({ gemini_api_key: e.target.value })} /></label>}
        {s.llm_backend === "anthropic_api" && <label className="field">Anthropic key<input type="password" defaultValue={s.anthropic_api_key} placeholder="Paste your key" onBlur={e => save({ anthropic_api_key: e.target.value })} /></label>}
        {s.llm_backend === "openai_api" && <label className="field">OpenAI key<input type="password" defaultValue={s.openai_api_key} placeholder="Paste your key" onBlur={e => save({ openai_api_key: e.target.value })} /></label>}
        {s.llm_backend === "ollama" && <Smith onReady={() => { load(); refresh(); }} />}
        {s.llm_backend === "claude_cli" && <><p className="small">Using your Claude Code login (personal use only).</p><ConnectClaude /></>}
      </section>

      <section className="card">
        <h2>While it works</h2>
        <div className="set-row"><div><strong>Show the browser</strong><p>Off keeps it in the background; watch any application live from Home or the bell.</p></div>
          <Switch on={s.browser_window === "visible"} label="Show the browser" onChange={v => save({ browser_window: v ? "visible" : "background" })} /></div>
        <div className="set-row"><div><strong>Notifications</strong><p>When something needs you or gets submitted.</p></div>
          <Switch on={!!s.notifications} label="Notifications" onChange={v => save({ notifications: v })} /></div>
        <div className="set-row"><div><strong>Research companies first</strong><p>Better answers; uses about twice the AI. <a href="#/stats">See usage</a></p></div>
          <Switch on={!!s.research_enabled} label="Research companies" onChange={v => save({ research_enabled: v })} /></div>
      </section>

      <ExtensionCard />

      <section className="card">
        <h2>Where jobs come from</h2>
        <p className="small muted">Jobsmith checks these lists for new roles on its own. You can add:</p>
        <ul className="small src-kinds">
          <li><strong>A GitHub job list</strong>, like SimplifyJobs' internship and new grad lists. Checked every few hours.</li>
          <li><strong>A company name</strong>, like "NVIDIA" or "Jane Street". Jobsmith finds their open roles that fit you and starts on them.</li>
          <li><strong>A link</strong> to one job or a careers page. Jobsmith reads it and starts the application.</li>
        </ul>
        <ul className="rows">{src.filter(x => x.active).map(x => (
          <li key={x.id} className="src"><Icon name="github" size={18} /><a className="grow" href={x.url} target="_blank" rel="noreferrer">{x.url.replace("https://github.com/", "")}</a>
            <span className="small muted">{x.last_synced ? `${x.last_count} roles` : "not checked yet"}</span>
            <button className="btn ghost sm" onClick={() => api.del(`/api/sources/${x.id}`).then(load)}>Remove</button></li>))}
        </ul>
        <div className="row">
          <input className="grow" placeholder="A GitHub list, a company name, or a job link" value={newSrc} onChange={e => setNewSrc(e.target.value)}
            onKeyDown={e => e.key === "Enter" && newSrc.trim() && addSource()} />
          <button className="btn primary" disabled={!newSrc.trim() || adding} onClick={addSource}>{adding ? "Adding…" : "Add"}</button>
        </div>
      </section>

      <details className="card more">
        <summary><h2>More options</h2></summary>
        <label className="check"><input type="checkbox" checked={s.multistep_beta} onChange={e => save({ multistep_beta: e.target.checked })} />
          <span>Multi-page sites like Workday (beta). You sign in yourself; Jobsmith never types passwords.</span></label>
        <label className="check"><input type="checkbox" checked={s.tailor_resume} onChange={e => save({ tailor_resume: e.target.checked })} />
          <span>Reorder my resume's bullets for each job (needs a LaTeX resume)</span></label>
        <label className="field">Research companies with
          <select value={s.research_backend} onChange={e => save({ research_backend: e.target.value })}>
            <option value="same">The same AI</option><option value="gemini_api">Gemini</option><option value="anthropic_api">Claude (API key)</option>
            <option value="openai_api">ChatGPT (API key)</option><option value="ollama">smith</option><option value="claude_cli">Claude Code login (personal use)</option>
          </select></label>
        {s.llm_backend !== "claude_cli" && <button className="link small" onClick={() => save({ llm_backend: "claude_cli" })}>Use my Claude Code login instead (personal use only)</button>}
      </details>
    </div>
  );
}

function ExtensionCard() {
  const [x, setX] = useState<{ path: string; exists: boolean; seen: number | null } | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.get<{ path: string; exists: boolean; seen: number | null }>("/api/ext/install").then(setX).catch(() => {}); }, []);
  if (!x?.exists) return null;
  const open = async () => {
    const r = await api.post<{ chrome: boolean; folder: boolean }>("/api/ext/open-install");
    setMsg(r.chrome || r.folder ? "Opened Chrome's extensions page and the folder. The folder path is copied too." : "Open chrome://extensions yourself, then pick the folder below.");
  };
  const copy = () => navigator.clipboard.writeText(x.path).then(() => setMsg("Folder path copied.")).catch(() => {});
  return (
    <section className="card" id="extension">
      <div className="card-h"><h2>Chrome extension</h2>{x.seen ? <span className="pill-on">installed</span> : <span className="tag quiet">not added yet</span>}</div>
      <p>A panel on every job posting: autofill from your profile, resume match, who you know there, your cover letter, and Write with Jobsmith beside open questions. It never submits.</p>
      <ol className="small steps-list">
        <li>In <code>chrome://extensions</code>, turn on Developer mode (top right).</li>
        <li>Click Load unpacked and choose <code className="path">{x.path}</code></li>
        <li>Pin Jobsmith from the puzzle-piece menu, then open any job posting.</li>
      </ol>
      <div className="row tight">
        <button className="btn primary sm" onClick={open}>Open Chrome's extensions page</button>
        <button className="btn sm" onClick={copy}>Copy the folder path</button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <p className="small muted">After you update Jobsmith, click the reload arrow on Jobsmith's card in chrome://extensions.</p>
    </section>
  );
}

