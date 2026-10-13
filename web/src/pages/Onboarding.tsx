import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Dots } from "../ui";
import Smith, { SmithLine } from "../components/Smith";

type Goal = { label: string; terms: string[]; sources: string[] };
type Detected = { kind: string; label: string; models?: string[] };
type Resume = { has_resume: boolean; pdf: string | null; name: string; email: string; school: string; degree: string;
  major: string; graduation: string; links: Record<string, string>; facts: number; to_confirm: number };
type State = { onboarded: boolean; goal: string; goals: Record<string, Goal>; fields: string[]; categories: string[];
  ai: { detected: Detected[]; ok: boolean; message: string; using: string; backend: string }; resume: Resume; autonomy: string };

const MANUAL: [string, string, string][] = [
  ["anthropic_api", "Claude, with an Anthropic API key", "From console.anthropic.com. Billed per use."],
  ["openai_api", "ChatGPT, with an OpenAI API key", "From platform.openai.com. A ChatGPT subscription doesn't include this."],
  ["gemini_api", "Gemini, with a Google AI Studio key", "From aistudio.google.com. Has a free tier."],
];
const STEPS = ["Your goal", "AI", "Resume", "How it applies", "First application"];

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const { status, refresh } = useContext(StatusCtx);
  const [st, setSt] = useState<State | null>(null);
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState("internship");
  const [cats, setCats] = useState<string[]>(["Software", "AI/ML/Data", "Hardware"]);
  const [ai, setAi] = useState("");
  const [key, setKey] = useState("");
  const [aiMsg, setAiMsg] = useState<{ ok: boolean; message: string } | null>(null);
  const [mode, setMode] = useState("autopilot");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api.get<State>("/api/onboarding").then(s => {
    setSt(s);
    if (s.goal) setGoal(s.goal);
    if (s.categories.length) setCats(s.categories);
    setAi(a => a || s.ai.detected.find(d => d.kind !== "ollama")?.kind || "ollama");
  });
  useEffect(() => { load(); }, []);
  if (!st) return <div className="onb"><p className="muted"><Dots />Loading</p></div>;

  const next = () => { setMsg(""); setStep(s => s + 1); };
  const saveGoal = async () => { setBusy(true); await api.post("/api/onboarding/goal", { goal, categories: cats }); setBusy(false); next(); };
  const saveAi = async () => {
    if (ai === "ollama") {           // smith: setup runs in the background while you keep going
      await api.post("/api/smith/setup", {}); refresh(); next(); return;
    }
    setBusy(true);
    const r = await api.post<{ ok: boolean; message: string }>("/api/onboarding/ai", { kind: ai, key });
    setAiMsg(r); setBusy(false); refresh();
    if (r.ok) next();
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setMsg("");
    const f = files[0];
    for (const slot of f.name.toLowerCase().endsWith(".pdf") ? ["resume", "resume_pdf"] : ["resume"]) {
      const fd = new FormData(); fd.append("file", f); fd.append("slot", slot);
      try { await api.post("/api/profile/upload", fd); } catch (e) { setMsg((e as Error).message); }
    }
    await load(); setBusy(false); refresh();
  };
  const finish = async () => { setBusy(true); await api.post("/api/onboarding/finish", { autonomy: mode }); setBusy(false); refresh(); next(); };
  const firstRun = async () => {
    setBusy(true);
    const r = await api.post<{ ok: boolean; message?: string; job_id?: string }>("/api/onboarding/first-run");
    setBusy(false);
    if (r.ok && r.job_id) { onDone(); location.hash = `#/matches/${r.job_id}`; } else setMsg(r.message ?? "Nothing to try yet.");
  };
  const skip = async () => { await api.post("/api/onboarding/finish", { autonomy: status?.autonomy ?? "copilot" }); refresh(); onDone(); };
  const r = st.resume;

  return (
    <div className="onb">
      <div className="onb-card">
        <p className="onb-step">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>

        {step === 0 && (<>
          <h1>What's your goal with Jobsmith?</h1>
          <p className="muted">It picks your job lists and how picky to be from this. You can change it later.</p>
          {Object.entries(st.goals).map(([k, g]) => (
            <label key={k} className={`choice ${goal === k ? "on" : ""}`}>
              <input type="radio" name="goal" checked={goal === k} onChange={() => setGoal(k)} />
              <div><strong>{g.label}</strong></div>
            </label>
          ))}
          <h3 className="onb-sub">Which fields?</h3>
          <div className="checks">{st.fields.map(f => (
            <label key={f} className="check"><input type="checkbox" checked={cats.includes(f)}
              onChange={e => setCats(e.target.checked ? [...cats, f] : cats.filter(x => x !== f))} />{f}</label>))}</div>
          <div className="onb-act"><button className="btn primary" onClick={saveGoal} disabled={busy || !cats.length}>Continue</button></div>
        </>)}

        {step === 1 && (<>
          <h1>Which AI should write your answers?</h1>
          <p className="muted">It only writes the open-ended answers. Contact details, work authorization and demographics always come straight from your profile.</p>
          {st.ai.detected.filter(d => d.kind !== "ollama").map(d => (
            <label key={d.kind} className={`choice ${ai === d.kind ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === d.kind} onChange={() => setAi(d.kind)} />
              <div><strong>{d.label}</strong><p>Found on this computer, ready to use.</p></div>
            </label>
          ))}
          <label className={`choice ${ai === "ollama" ? "on" : ""}`}>
            <input type="radio" name="ai" checked={ai === "ollama"} onChange={() => { setAi("ollama"); setAiMsg(null); }} />
            <div><strong>smith</strong> <span className="muted">(free, recommended)</span>
              <p>Jobsmith's own AI. Runs on this computer, so nothing you write leaves it.</p>
              {ai === "ollama" && <Smith compact noButton />}</div>
          </label>
          {MANUAL.filter(([k]) => !st.ai.detected.some(d => d.kind === k)).map(([k, label, hint]) => (
            <label key={k} className={`choice ${ai === k ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === k} onChange={() => { setAi(k); setKey(""); setAiMsg(null); }} />
              <div><strong>{label}</strong><p>{hint}</p>
                {ai === k && k !== "ollama" && <input type="password" className="onb-key" placeholder="Paste the key" value={key} onChange={e => setKey(e.target.value)} />}</div>
            </label>
          ))}
          {aiMsg && <p className={aiMsg.ok ? "ok-text" : "warn-text"}>{aiMsg.message}</p>}
          <div className="onb-act">
            <button className="btn primary" onClick={saveAi} disabled={busy}>{busy ? <Dots /> : ai === "ollama" ? "Continue" : "Connect"}</button>
            <button className="link" onClick={next}>Skip for now</button>
          </div>
        </>)}

        {step === 2 && (<>
          <h1>Add your resume</h1>
          <p className="muted">Everything else fills itself in from it: your details, links, experience and skills. A LaTeX .tex is read most exactly; a PDF also becomes the file employers get.</p>
          <label className="drop">
            <input type="file" accept=".tex,.pdf,.docx,.txt,.md" onChange={e => { upload(e.target.files); e.target.value = ""; }} />
            {busy ? <span><Dots />Reading your resume</span> : <span><strong>Choose a file</strong> or drop it here</span>}
          </label>
          {msg && <p className="warn-text">{msg}</p>}
          {r.has_resume && (
            <div className="found">
              <p><strong>{r.name || "Your name"}</strong>{r.email ? `, ${r.email}` : ""}</p>
              <p>{[r.degree, r.major].filter(Boolean).join(" in ")}{r.school ? `, ${r.school}` : ""}{r.graduation ? `, graduating ${r.graduation}` : ""}</p>
              {Object.entries(r.links).map(([k, v]) => <p key={k}><span className="muted">{k}:</span> {v}</p>)}
              <p>{r.facts} facts about your experience, projects and skills.</p>
              {!r.pdf && <p className="warn-text">Employers get a PDF. Add the PDF version too when you have it.</p>}
            </div>
          )}
          <div className="onb-act">
            {r.has_resume && r.to_confirm > 0 && (
              <button className="btn primary" onClick={() => api.post("/api/answers/confirm-all").then(() => { load(); next(); })}>Looks right, continue</button>)}
            {r.has_resume && r.to_confirm === 0 && <button className="btn primary" onClick={next}>Continue</button>}
            <a className="link" href="#/profile" onClick={onDone}>Fix details in Profile</a>
          </div>
        </>)}

        {step === 3 && (<>
          <h1>How should Jobsmith apply?</h1>
          <label className={`choice ${mode === "autopilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "autopilot"} onChange={() => setMode("autopilot")} />
            <div><strong>Autopilot</strong> <span className="muted">(recommended)</span>
              <p>Checks your job lists every few hours, applies to good fits you qualify for, and holds anything it isn't sure about for one click from you. Stops at 25 a day.</p></div>
          </label>
          <label className={`choice ${mode === "copilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "copilot"} onChange={() => setMode("copilot")} />
            <div><strong>Copilot</strong><p>Fills every form and stops before Submit. You press it.</p></div>
          </label>
          <p className="small muted">You're responsible for what's sent in your name. CAPTCHAs, sign-ins and emailed codes always come to you.</p>
          <div className="onb-act"><button className="btn primary" onClick={finish} disabled={busy}>Continue</button></div>
        </>)}

        {step === 4 && (<>
          <h1>Watch it fill your first application</h1>
          <p className="muted">Jobsmith picks your best match and fills it in a browser window in front of you. It won't submit this one, so you can check every box first.</p>
          {msg && <p className="warn-text">{msg} Your job lists may still be syncing; try again in a minute.</p>}
          <div className="onb-act">
            <button className="btn primary" onClick={firstRun} disabled={busy}>{busy ? <Dots /> : "Fill my first application"}</button>
            <button className="link" onClick={onDone}>Go to Jobsmith</button>
          </div>
        </>)}

        {step >= 2 && <SmithLine />}
        {step < 4 && <p className="onb-skip"><button className="link small" onClick={skip}>Skip setup</button></p>}
      </div>
    </div>
  );
}
