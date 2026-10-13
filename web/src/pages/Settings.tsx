import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import ConnectClaude from "../components/ConnectClaude";
import Smith from "../components/Smith";
import { Icon } from "../ui";


type S = Record<string, any>;
type Source = { id: number; url: string; active: number; last_synced: number | null; last_count: number | null };
const CATS = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"];

export default function Settings() {
  const { refresh, status } = useContext(StatusCtx);
  const [s, setS] = useState<S | null>(null);
  const [src, setSrc] = useState<Source[]>([]);
  const [newSrc, setNewSrc] = useState("");
  const [saved, setSaved] = useState("");
  const load = () => { api.get<S>("/api/settings").then(setS); api.get<Source[]>("/api/sources").then(setSrc); };
  useEffect(load, []);
  if (!s) return <div className="page"><p className="muted">Loading…</p></div>;

  const save = async (patch: S) => {
    const next = await api.put<S>("/api/settings", patch);
    setS(next); setSaved("Saved"); refresh(); setTimeout(() => setSaved(""), 1500);
  };
  const list = (k: string) => (e: { target: { value: string } }) =>
    save({ [k]: e.target.value.split(",").map(x => x.trim()).filter(Boolean) });
  const num = (k: string) => (e: { target: { value: string } }) => save({ [k]: Number(e.target.value) });

  return (
    <div className="page narrow settings">
      <div className="page-h"><div><h1>Settings</h1><p className="muted">{saved || "Changes save as you make them."}</p></div></div>

      <section className="card">
        <h2>How Jobsmith applies</h2>
        <label className={`choice ${s.autonomy !== "copilot" ? "on" : ""}`}>
          <input type="radio" checked={s.autonomy !== "copilot"} onChange={() => save({ autonomy: "autopilot", auto_run: true })} />
          <div><strong>Autopilot</strong> <span className="muted">(recommended)</span>
            <p>Applies on its own: researches the company, answers from your profile, fills the form and submits. Anything it isn't sure about (an AI answer below
              <input className="tiny" type="number" min={0} max={1} step={0.05} value={s.autopilot_min_confidence} onChange={e => save({ autopilot_min_confidence: Number(e.target.value) })} /> confidence,
              an empty required field, a field it couldn't fill) waits for one click from you.</p></div>
        </label>
        <label className={`choice ${s.autonomy === "copilot" ? "on" : ""}`}>
          <input type="radio" checked={s.autonomy === "copilot"} onChange={() => save({ autonomy: "copilot" })} />
          <div><strong>Copilot</strong><p>Fills every form and stops before Submit. You review each tab and click Submit yourself.</p></div>
        </label>
        <p className="small muted">You're responsible for what's submitted in your name. CAPTCHAs, sign-ins and emailed codes always come to you.</p>
        <label className="check"><input type="checkbox" checked={s.auto_run} onChange={e => save({ auto_run: e.target.checked })} />
          <span>Check my job lists every <input className="tiny" type="number" min={1} value={s.auto_interval_hours} onChange={num("auto_interval_hours")} /> hours
            and start up to <input className="tiny" type="number" min={1} value={s.auto_max_per_run} onChange={num("auto_max_per_run")} /> of the best new matches. Runs while Jobsmith is open and your Mac is awake.</span></label>
        <label className="check"><span>Only apply to roles with fit of at least <input className="tiny" type="number" min={0} max={100} value={s.min_fit_score} onChange={num("min_fit_score")} /></span></label>
        <div className="row"><button className="btn" onClick={() => api.post<{ summary: string }>("/api/auto/run-now").then(r => { setSaved(r.summary); refresh(); })}>Run once now</button>
          {status?.auto.last_summary && <span className="small muted">Last run: {status.auto.last_summary}</span>}</div>
      </section>

      <section className="card">
        <h2>Limits</h2>
        <div className="grid-2 tight">
          <label className="field">Applications per day<input type="number" min={1} value={s.max_applications_per_day} onChange={num("max_applications_per_day")} /></label>
          <label className="field">Per company<input type="number" min={1} value={s.max_applications_per_company} onChange={num("max_applications_per_company")} /></label>
          <label className="field">Forms filled at once<input type="number" min={1} max={6} value={s.concurrency} onChange={num("concurrency")} /></label>
          <label className="field">AI calls at once<input type="number" min={1} max={8} value={s.llm_concurrency} onChange={num("llm_concurrency")} /></label>
        </div>
        
      </section>

      <section className="card">
        <h2>AI</h2>
        <label className="field">Writes your answers with
          <select value={s.llm_backend} onChange={e => save({ llm_backend: e.target.value })}>
            <option value="auto">Whatever's available (API key, then smith)</option>
            <option value="ollama">smith, on this computer (free, private)</option>
            <option value="anthropic_api">Claude, with an Anthropic API key</option>
            <option value="openai_api">ChatGPT, with an OpenAI API key</option>
            <option value="gemini_api">Gemini, with a Google AI Studio key</option>
            <option value="claude_cli">Claude Code login (personal use only)</option>
          </select></label>
        {status && <p className="small">Using <strong>{status.llm.writing.label}</strong>{status.llm.writing.ok ? "." : `: ${status.llm.writing.message}`}</p>}
        {s.llm_backend === "claude_cli" && <p className="small warn-text">Anthropic doesn't allow Claude subscription logins in third-party apps, so this is for your own use. Use an API key or smith for anything you share.</p>}
        {s.llm_backend === "claude_cli" && <ConnectClaude />}
        {s.llm_backend === "claude_cli" && s.claude_connected_in_app && (
          <button className="btn ghost sm" onClick={() => api.post("/api/claude/disconnect").then(() => { load(); refresh(); })}>Disconnect Claude</button>)}
        {["claude_cli", "anthropic_api"].includes(s.llm_backend) && (
          <label className="field">Claude model
            <select value={s.llm_model} onChange={e => save({ llm_model: e.target.value })}>
              <option value="sonnet">Sonnet (recommended)</option><option value="opus">Opus (best writing, uses more)</option><option value="haiku">Haiku (fastest, least usage)</option>
            </select></label>)}
        {["anthropic_api", "auto"].includes(s.llm_backend) && (
          <label className="field">Anthropic API key<input type="password" defaultValue={s.anthropic_api_key} placeholder="or set ANTHROPIC_API_KEY" onBlur={e => save({ anthropic_api_key: e.target.value })} /></label>)}
        {["openai_api", "auto"].includes(s.llm_backend) && (
          <label className="field">OpenAI API key<input type="password" defaultValue={s.openai_api_key} placeholder="or set OPENAI_API_KEY" onBlur={e => save({ openai_api_key: e.target.value })} /></label>)}
        {s.llm_backend === "openai_api" && (
          <label className="field">OpenAI model<input defaultValue={s.openai_model} onBlur={e => save({ openai_model: e.target.value })} /></label>)}
        {["gemini_api", "auto"].includes(s.llm_backend) && (
          <label className="field">Gemini API key<input type="password" defaultValue={s.gemini_api_key} placeholder="or set GEMINI_API_KEY" onBlur={e => save({ gemini_api_key: e.target.value })} /></label>)}
        {s.llm_backend === "gemini_api" && (
          <label className="field">Gemini model<input defaultValue={s.gemini_model} onBlur={e => save({ gemini_model: e.target.value })} /></label>)}
        {s.llm_backend === "ollama" && <Smith onReady={() => { load(); refresh(); }} />}
        {s.llm_backend === "ollama" && (
          <label className="field">smith's model<input defaultValue={s.ollama_model} placeholder="blank picks one for this computer" onBlur={e => save({ ollama_model: e.target.value.trim() })} />
            <span className="small muted">Any Ollama model works. smith runs through Ollama; set OLLAMA_HOST to use one on a Mac mini.</span></label>)}
        {s.llm_backend === "ollama" && <p className="small muted">smith can't search the web, so company research uses only the posting. Pick a cloud AI below for research if you want it.</p>}
        <label className="field">Researches companies with
          <select value={s.research_backend} onChange={e => save({ research_backend: e.target.value })}>
            <option value="same">The same AI</option>
            <option value="anthropic_api">Claude, with an Anthropic API key</option>
            <option value="openai_api">ChatGPT, with an OpenAI API key</option>
            <option value="gemini_api">Gemini, with a Google AI Studio key</option>
            <option value="ollama">smith (no web search)</option>
            <option value="claude_cli">Claude Code login (personal use only)</option>
          </select></label>
        {(s.research_backend === "openai_api" && s.llm_backend !== "openai_api") && (
          <label className="field">OpenAI API key<input type="password" defaultValue={s.openai_api_key} onBlur={e => save({ openai_api_key: e.target.value })} /></label>)}
        {(s.research_backend === "anthropic_api" && s.llm_backend !== "anthropic_api") && (
          <label className="field">Anthropic API key<input type="password" defaultValue={s.anthropic_api_key} onBlur={e => save({ anthropic_api_key: e.target.value })} /></label>)}
        {(s.research_backend === "gemini_api" && s.llm_backend !== "gemini_api") && (
          <label className="field">Gemini API key<input type="password" defaultValue={s.gemini_api_key} onBlur={e => save({ gemini_api_key: e.target.value })} /></label>)}
        {s.research_backend === "claude_cli" && s.llm_backend !== "claude_cli" && <ConnectClaude />}
        <label className="check"><input type="checkbox" checked={s.research_enabled} onChange={e => save({ research_enabled: e.target.checked })} />
          <span>Research each company before applying (better answers, about twice the AI usage). <a href="#/stats">See usage</a></span></label>
      </section>

      <section className="card">
        <h2>Browser</h2>
        <label className={`choice ${s.browser_window !== "visible" ? "on" : ""}`}><input type="radio" checked={s.browser_window !== "visible"} onChange={() => save({ browser_window: "background" })} />
          <div><strong>In the background</strong><p>The browser window stays minimized. Watch each application live on the Autopilot page and take over when you want.</p></div></label>
        <label className={`choice ${s.browser_window === "visible" ? "on" : ""}`}><input type="radio" checked={s.browser_window === "visible"} onChange={() => save({ browser_window: "visible" })} />
          <div><strong>Visible</strong><p>The browser window stays up while it works.</p></div></label>
        <label className="check"><input type="checkbox" checked={s.multistep_beta} onChange={e => save({ multistep_beta: e.target.checked })} />
          <span>Multi-page sites like Workday (beta). You sign in yourself; Jobsmith never types passwords.</span></label>
        <label className="check"><input type="checkbox" checked={s.tailor_resume} onChange={e => save({ tailor_resume: e.target.checked })} />
          <span>Tailor my resume per job: same words, most relevant bullets first (needs <code>brew install tectonic</code>)</span></label>
        <label className="check"><input type="checkbox" checked={s.notifications} onChange={e => save({ notifications: e.target.checked })} />
          <span>Mac notifications when something needs me or gets submitted</span></label>
      </section>

      <section className="card">
        <h2>What to look for</h2>
        <div className="checks">{CATS.map(c => (
          <label key={c} className="check"><input type="checkbox" checked={s.target_categories.includes(c)}
            onChange={e => save({ target_categories: e.target.checked ? [...s.target_categories, c] : s.target_categories.filter((x: string) => x !== c) })} />{c}</label>))}</div>
        <label className="field">Seasons, comma separated<input defaultValue={s.target_terms.join(", ")} onBlur={list("target_terms")} /></label>
        <label className="field">Locations, comma separated (blank means anywhere)<input defaultValue={s.target_locations.join(", ")} onBlur={list("target_locations")} placeholder="e.g. CA, New York, Remote" /></label>
        <label className="field">Never apply to<input defaultValue={s.exclude_companies.join(", ")} onBlur={list("exclude_companies")} /></label>
      </section>

      <section className="card">
        <h2>Job lists</h2>
        <ul className="rows">{src.filter(x => x.active).map(x => (
          <li key={x.id} className="src"><Icon name="github" size={18} /><a className="grow" href={x.url} target="_blank" rel="noreferrer">{x.url.replace("https://github.com/", "")}</a>
            <span className="small muted">{x.last_synced ? `${x.last_count} roles` : "not synced"}</span>
            <button className="btn ghost sm" onClick={() => api.del(`/api/sources/${x.id}`).then(load)}>Remove</button></li>))}
        </ul>
        <div className="row">
          <input className="grow" placeholder="https://github.com/SimplifyJobs/New-Grad-Positions" value={newSrc} onChange={e => setNewSrc(e.target.value)} />
          <button className="btn primary" disabled={!newSrc} onClick={() => api.post("/api/sources", { url: newSrc }).then(() => { setNewSrc(""); load(); })}>Add list</button>
        </div>
      </section>

      <section className="card">
        <h2>Track replies with Gmail</h2>
        <p className="small muted">Read-only. Jobsmith reads recent emails to spot confirmations, assessments, interviews and rejections, and moves them on the Tracker.
          Use a Google <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">app password</a>, not your normal password.</p>
        <div className="grid-2 tight">
          <label className="field">Gmail address<input defaultValue={s.gmail_address} onBlur={e => save({ gmail_address: e.target.value.trim() })} /></label>
          <label className="field">App password<input type="password" defaultValue={s.gmail_app_password} onBlur={e => save({ gmail_app_password: e.target.value })} /></label>
        </div>
        <button className="btn" onClick={() => api.post<{ error?: string; checked?: number; new_outcomes?: number }>("/api/outcomes/check")
          .then(r => setSaved(r.error ?? `Checked ${r.checked} emails, ${r.new_outcomes} new replies matched`))}>Check now</button>
      </section>
    </div>
  );
}
