import { useContext, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Dots, poll } from "../ui";
import Smith, { SmithLine } from "../components/Smith";
import { AsciiSmith } from "../brand";

type Detected = { kind: string; label: string; models?: string[] };
type Check = { key: string; label: string; required: boolean; value: string; done: boolean };
type ReadBack = { key: string; label: string; value: string; confirmed: boolean; section: string };
type Question = { key: string; label: string; why: string; kind: "choice" | "text"; choices?: string[]; required?: boolean;
  default?: string; placeholder?: string; value: string; confirmed: boolean; hint?: string };
type Preset = { key: string; label: string; level: string; url: string; on: boolean };
type Preview = { matches: number; open: number; bar: number; advice: string;
  outside: { level: number; role: number; place: number; age: number } };
type State = {
  goals_set: string[]; companies: string[]; fields: string[]; categories: string[]; locations: string[];
  location_choices: string[]; checklist: Check[]; setup_step: string; autonomy: string; picky: string;
  ai: { detected: Detected[]; ok: boolean; message: string; using: string; backend: string };
  smith: { has_model: boolean; model: string };
  steps: string[]; step_done: Record<string, boolean>; read_back: ReadBack[]; questions: Question[];
  presets: Preset[]; seasons: string[]; seasons_set: string[]; prefs_saved: boolean;
  resume: { has_resume: boolean; pdf: string | null; facts: number };
};

const KEYS: [string, string, string][] = [
  ["gemini_api", "Gemini", "Free, writes well, and can research companies on the web. Takes a minute: sign in with Google and create a key."],
  ["anthropic_api", "Claude, with an Anthropic API key", "From console.anthropic.com. Billed per use."],
  ["openai_api", "ChatGPT, with an OpenAI API key", "From platform.openai.com. A ChatGPT subscription doesn't include this."],
];
const KEY_URL: Record<string, string> = { gemini_api: "https://aistudio.google.com/apikey",
  anthropic_api: "https://console.anthropic.com/settings/keys", openai_api: "https://platform.openai.com/api-keys" };
const TITLES: Record<string, string> = { resume: "Your resume", confirm: "Check what we read", questions: "Questions forms ask",
  prefs: "What you're looking for", sources: "Where to look", ai: "Writing help (optional)", start: "Your first application" };
const LEVELS: [string, string][] = [["internship", "Internship"], ["newgrad", "New grad"]];
const PICKY: [string, string, string][] = [["strong", "Strong fits", "fewer, closer matches"], ["good", "Good fits", "recommended"],
  ["any", "Anything I qualify for", "the most"]];

function firstStep(s: State): number {
  if (s.setup_step === "restart") return 0;          // "Run setup again": from the top, with everything filled in
  const i = s.steps.findIndex(k => !s.step_done[k]);
  return i < 0 ? s.steps.length - 1 : i;
}

export default function Onboarding({ onDone, start: startAt }: { onDone: () => void; start?: number }) {
  const { refresh } = useContext(StatusCtx);
  const [st, setSt] = useState<State | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // step 2: what the resume gave, as you correct it
  const [vals, setVals] = useState<Record<string, string>>({});
  // step 3: the one list, and optional saved answers
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [essays, setEssays] = useState<Record<string, string>>({});
  // step 4: what you're looking for
  const [levels, setLevels] = useState<string[]>(["internship"]);
  const [seasons, setSeasons] = useState<string[]>(["Summer 2027"]);
  const [cats, setCats] = useState<string[]>(["Software", "AI/ML/Data"]);
  const [places, setPlaces] = useState<string[]>([]);
  const [picky, setPicky] = useState("good");
  const [preview, setPreview] = useState<Preview | null>(null);
  // step 5
  const [presets, setPresets] = useState<string[]>([]);
  // step 6
  const [ai, setAi] = useState("");
  const [key, setKey] = useState("");
  const [aiMsg, setAiMsg] = useState<{ ok: boolean; message: string } | null>(null);
  const [mode, setMode] = useState("autopilot");

  const load = () => api.get<State>("/api/onboarding").then(s => {
    setSt(s);
    setStep(cur => cur ?? (startAt != null ? Math.min(startAt, s.steps.length - 1) : firstStep(s)));
    return s;
  });
  useEffect(() => {
    load().then(s => {
      if (s.goals_set.filter(g => g !== "targeted").length) setLevels(s.goals_set.filter(g => g !== "targeted"));
      if (s.seasons_set.length) setSeasons(s.seasons_set);
      if (s.prefs_saved && s.categories.length) setCats(s.categories);
      if (s.location_choices.length) setPlaces(s.location_choices);
      if (s.picky) setPicky(s.picky);
      if (s.autonomy) setMode(s.autonomy);
      const found = s.ai.detected.find(d => d.kind !== "ollama")?.kind;
      setAi(found || (s.smith.has_model ? "ollama" : "gemini_api"));
    });
  }, []);
  // The resume step updates as files are read (and as the terminal changes things).
  useEffect(() => { if (step !== 0) return; const t = poll(load, 2000); return () => t.stop(); }, [step]);
  // The live count: asked again shortly after each change, nothing saved.
  const asked = useRef(0), again = useRef(0);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (step !== 3) return;
    const n = ++asked.current;
    const t = setTimeout(() => api.post<Preview>("/api/onboarding/preview", { levels, seasons, categories: cats, locations: places, picky })
      .then(p => { if (n !== asked.current) return; setPreview(p);
        // a fresh install: the lists are being read now, so ask again until listings arrive
        if (p.open === 0) again.current = window.setTimeout(() => setTick(x => x + 1), 2500); }), 150);
    return () => { clearTimeout(t); clearTimeout(again.current); };
  }, [step, levels.join(), seasons.join(), cats.join(), places.join(), picky, tick]);
  useEffect(() => {
    if (!st || step !== 4) return;
    const on = st.presets.filter(p => levels.includes(p.level)).map(p => p.key);
    setPresets(on);
  }, [step]);

  if (!st || step == null) return <div className="onb"><p className="muted"><Dots />Loading</p></div>;
  const steps = st.steps;
  const cur = steps[step];
  const next = () => { setMsg(""); setStep(s => Math.min((s ?? 0) + 1, steps.length - 1)); };
  const back = () => { setMsg(""); setStep(s => Math.max((s ?? 0) - 1, 0)); };
  const toggle = (list: string[], v: string) => list.includes(v) ? list.filter(x => x !== v) : [...list, v];

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setMsg("");
    const list = Array.from(files);
    const isPdf = (f: File) => f.name.toLowerCase().endsWith(".pdf");
    // A .tex or .docx alongside the PDF is the better source to read; the PDF is then only what gets attached.
    const hasSource = list.some(f => !isPdf(f));
    for (const f of [...list.filter(f => !isPdf(f)), ...list.filter(isPdf)]) {
      for (const slot of isPdf(f) ? (hasSource ? ["resume_pdf"] : ["resume", "resume_pdf"]) : ["resume"]) {
        const fd = new FormData(); fd.append("file", f); fd.append("slot", slot);
        try { await api.post("/api/profile/upload", fd); } catch (e) { setMsg((e as Error).message); }
      }
    }
    const s = await load(); setBusy(false); refresh();
    setVals(Object.fromEntries(s.read_back.map(r => [r.key, r.value])));
  };
  const confirmRead = async () => {
    setBusy(true);
    const all = Object.fromEntries(st.read_back.map(r => [r.key, vals[r.key] ?? r.value]));
    await api.post("/api/onboarding/confirm", { values: all });
    await load(); setBusy(false); next();
  };
  const answerOf = (q: Question) => answers[q.key] ?? (q.value || q.default || "");
  const questionsMissing = st.questions.filter(q => q.required && !answerOf(q));
  const saveQuestions = async () => {
    setBusy(true);
    await api.post("/api/onboarding/questions", { values: Object.fromEntries(st.questions.map(q => [q.key, answerOf(q)])) });
    for (const [k, v] of Object.entries(essays)) if (v.trim()) await api.put(`/api/essays/${k}`, { text: v.trim() });
    await load(); setBusy(false); next();
  };
  const saveLooking = async () => {
    setBusy(true);
    await api.post("/api/onboarding/looking", { levels, seasons, categories: cats, locations: places, picky });
    await load(); setBusy(false); next();
  };
  const saveSources = async () => {
    setBusy(true);
    await api.post("/api/onboarding/sources", { presets });
    await load(); setBusy(false); next();
  };
  const saveAi = async (skip = false) => {
    if (!skip && ai === "ollama") { await api.post("/api/smith/setup", {}); await api.post("/api/onboarding/ai", { kind: "skip" }); refresh(); next(); return; }
    setBusy(true);
    const r = await api.post<{ ok: boolean; message: string }>("/api/onboarding/ai", skip ? { kind: "skip" } : { kind: ai, key });
    setAiMsg(skip ? null : r); setBusy(false); refresh();
    if (r.ok || skip) { await load(); next(); }
  };
  const start = async () => {
    setBusy(true);
    await api.post("/api/onboarding/finish", { autonomy: mode, final: false });
    const r = mode === "copilot"
      ? await api.post<{ ok: boolean; message?: string; job_id?: string }>("/api/onboarding/first-run")
      : await api.post<{ ok: boolean; message?: string }>("/api/onboarding/start");
    setBusy(false); refresh();
    if (r.ok === false) { setMsg(r.message ?? "Nothing to fill yet. Your job lists may still be syncing; try again in a minute."); return; }
    onDone(); location.hash = "#/";
  };
  const skipSetup = async () => { await api.post("/api/onboarding/skip"); refresh(); onDone(); };
  const done = st.step_done;
  const count = preview?.matches;

  return (
    <div className="onb">
      <div className="onb-art" aria-hidden={step > 0}><AsciiSmith reveal={step === 0} />
        <p className="small muted">About ten minutes. Nothing is drafted or sent until you finish, and the first application waits for you.</p></div>
      <div className="onb-card">
        <ol className="onb-steps" aria-label="Setup steps">{steps.map((k, i) => (
          <li key={k} className={i === step ? "on" : done[k] ? "done" : ""} aria-current={i === step ? "step" : undefined}>
            <button className="link" disabled={i > step && !done[steps[i - 1]]} onClick={() => setStep(i)}>{TITLES[k]}</button></li>))}
        </ol>
        <p className="onb-step">Step {step + 1} of {steps.length}</p>

        {cur === "resume" && (<>
          <h1>Start with your resume</h1>
          <p className="muted">The PDF is what employers get. Everything Jobsmith writes comes from it, and nothing else about you is made up.</p>
          <label className="drop">
            <input type="file" multiple accept=".pdf,.tex,.docx" aria-label="Choose your resume"
              onChange={e => { upload(e.target.files); e.target.value = ""; }} />
            {busy ? <span><Dots />Reading your resume</span>
              : st.resume.pdf ? <span><strong>{st.resume.pdf}</strong> · {st.resume.facts} facts read. Drop a new one to replace it.</span>
              : <span><strong>Choose your resume PDF</strong> or drop it here</span>}
          </label>
          <p className="small muted">Have the LaTeX (.tex) or Word file too? Add it with the PDF: it's read more exactly.</p>
          {msg && <p className="warn-text">{msg}</p>}
          <div className="onb-act">
            <button className="btn primary" disabled={busy || !done.resume} onClick={() => {
              setVals(Object.fromEntries(st.read_back.map(r => [r.key, r.value]))); next(); }}>Continue</button>
          </div>
        </>)}

        {cur === "confirm" && (<>
          <h1>Check what we read</h1>
          <p className="muted">These go into forms exactly as written here. Fix anything that's wrong; leave a box empty if it doesn't apply.</p>
          <div className="readback">{st.read_back.map(r => (
            <label key={r.key} className="field rb-row">
              <span>{r.label}</span>
              <input value={vals[r.key] ?? r.value} onChange={e => setVals({ ...vals, [r.key]: e.target.value })}
                placeholder={r.value ? "" : "Not on your resume"} />
            </label>))}
          </div>
          <div className="onb-act">
            <button className="btn primary" disabled={busy || !(vals.first_name ?? st.read_back.find(r => r.key === "first_name")?.value)
              || !(vals.email ?? st.read_back.find(r => r.key === "email")?.value)} onClick={confirmRead}>
              {busy ? <Dots /> : "These are right"}</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {cur === "questions" && (<>
          <h1>Questions forms ask</h1>
          <p className="muted">Answer these once and every application uses them. Most have a sensible default; the first three only you can answer.</p>
          <div className="qlist">{st.questions.map(q => {
            const v = answerOf(q);
            return (
              <div key={q.key} className={`q ${q.required && !v ? "need" : ""}`} role="group" aria-label={q.label}>
                <div className="q-h"><strong>{q.label}</strong>{q.required && <span className="small muted"> · required</span>}</div>
                <p className="small muted q-why">{q.why}{q.hint && <> <span className="q-hint">{q.hint}.</span></>}</p>
                {q.kind === "choice" ? (
                  <div className="chips">{q.choices!.map(c => (
                    <button key={c} className={`chip ${v === c ? "on" : ""}`} aria-pressed={v === c}
                      onClick={() => setAnswers({ ...answers, [q.key]: c })}>{c}</button>))}</div>
                ) : (
                  <input className="q-in" value={v} placeholder={q.placeholder} aria-label={q.label}
                    onChange={e => setAnswers({ ...answers, [q.key]: e.target.value })} />)}
              </div>);
          })}</div>
          <details className="q-more">
            <summary>Saved answers <span className="muted small">(optional)</span></summary>
            <p className="small muted">Your own words for questions many forms ask. Used exactly as written; without them, those boxes wait for you or are left empty when optional.</p>
            {[["additional_info", "Additional information"], ["why_role", "Why this role?"]].map(([k, label]) => (
              <label key={k} className="field">{label}
                <textarea rows={3} value={essays[k] ?? ""} onChange={e => setEssays({ ...essays, [k]: e.target.value })} /></label>))}
          </details>
          <div className="onb-act">
            <button className="btn primary" disabled={busy || questionsMissing.length > 0} onClick={saveQuestions}>
              {busy ? <Dots /> : questionsMissing.length ? `Answer ${questionsMissing.length} more to continue` : "Save and continue"}</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {cur === "prefs" && (<>
          <h1>What you're looking for</h1>
          <p className="muted">Only roles inside these count as matches. Aim for tens to a couple of hundred.</p>
          <h3 className="onb-sub">Level</h3>
          <div className="chips">{LEVELS.map(([k, label]) => (
            <button key={k} className={`chip ${levels.includes(k) ? "on" : ""}`} aria-pressed={levels.includes(k)}
              onClick={() => setLevels(toggle(levels, k).length ? toggle(levels, k) : levels)}>{label}</button>))}</div>
          {levels.includes("internship") && st.seasons.length > 1 && (<>
            <p className="small muted onb-hint">Internship seasons</p>
            <div className="chips">{st.seasons.map(t => (
              <button key={t} className={`chip ${seasons.includes(t) ? "on" : ""}`} aria-pressed={seasons.includes(t)}
                onClick={() => setSeasons(toggle(seasons, t).length ? toggle(seasons, t) : seasons)}>{t}</button>))}</div></>)}
          <h3 className="onb-sub">Role types</h3>
          <div className="chips">{st.fields.map(f => (
            <button key={f} className={`chip ${cats.includes(f) ? "on" : ""}`} aria-pressed={cats.includes(f)}
              onClick={() => setCats(toggle(cats, f).length ? toggle(cats, f) : cats)}>{f}</button>))}</div>
          <h3 className="onb-sub">Places</h3>
          <div className="chips">
            <button className={`chip ${places.length === 0 ? "on" : ""}`} aria-pressed={places.length === 0} onClick={() => setPlaces([])}>Anywhere in the US</button>
            {st.locations.map(p => (
              <button key={p} className={`chip ${places.includes(p) ? "on" : ""}`} aria-pressed={places.includes(p)}
                onClick={() => setPlaces(toggle(places, p))}>{p}</button>))}
          </div>
          <h3 className="onb-sub">How good a fit</h3>
          <div className="chips">{PICKY.map(([k, label, hint]) => (
            <button key={k} className={`chip ${picky === k ? "on" : ""}`} aria-pressed={picky === k} title={hint}
              onClick={() => setPicky(k)}>{label}</button>))}</div>
          <div className="count" role="status" aria-live="polite">
            <span className="count-n">{count == null ? "…" : count.toLocaleString()}</span>
            <span><strong>{count === 1 ? "match" : "matches"}</strong>{preview && preview.open > 0 &&
              <span className="small muted"> of {preview.open.toLocaleString()} open roles in your lists</span>}
              {preview?.advice && <span className="small warn-text count-advice">{preview.advice}</span>}
              {preview && preview.open === 0 && <span className="small muted count-advice">Your job lists are still syncing; the count fills in as they arrive.</span>}
            </span>
          </div>
          {preview && preview.open > 0 && (
            <p className="small muted">Left out: {[["level", "other levels or seasons"], ["role", "other role types"], ["place", "other places"], ["age", "posted over 60 days ago"]]
              .filter(([k]) => preview.outside[k as keyof Preview["outside"]] > 0)
              .map(([k, w]) => `${preview.outside[k as keyof Preview["outside"]].toLocaleString()} ${w}`).join(" · ") || "nothing"}</p>)}
          <div className="onb-act">
            <button className="btn primary" disabled={busy} onClick={saveLooking}>{busy ? <Dots /> : "Continue"}</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {cur === "sources" && (<>
          <h1>Where to look</h1>
          <p className="muted">Lists Jobsmith reads every few hours. The one for your level is already on.</p>
          {st.presets.map(p => (
            <label key={p.key} className={`choice ${presets.includes(p.key) ? "on" : ""}`}>
              <input type="checkbox" checked={presets.includes(p.key)} onChange={() => setPresets(toggle(presets, p.key))} />
              <div><strong>{p.label}</strong><p>{p.level === "internship" ? "Thousands of internships, kept up to date by the community." : "Full-time roles for recent graduates, kept up to date by the community."}</p></div>
            </label>))}
          <p className="small muted">Want one company's own job board too? Add it later in Settings, Job lists.</p>
          <div className="onb-act">
            <button className="btn primary" disabled={busy || presets.length === 0} onClick={saveSources}>{busy ? <Dots /> : "Continue"}</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {cur === "ai" && (<>
          <h1>Writing help (optional)</h1>
          <p className="muted">An AI writes the open-ended answers, always from your resume. Contact details, work authorization and demographics never go through it. Without one, those answers wait for you.</p>
          {st.ai.detected.filter(d => d.kind !== "ollama").map(d => (
            <label key={d.kind} className={`choice ${ai === d.kind ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === d.kind} onChange={() => setAi(d.kind)} />
              <div><strong>{d.label}</strong><p>Already set up on this computer.</p></div>
            </label>))}
          {KEYS.filter(([k]) => !st.ai.detected.some(d => d.kind === k)).map(([k, label, hint]) => (
            <label key={k} className={`choice ${ai === k ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === k} onChange={() => { setAi(k); setKey(""); setAiMsg(null); }} />
              <div><strong>{label}</strong>{k === "gemini_api" && <span className="muted"> (free, recommended)</span>}<p>{hint}</p>
                {ai === k && <>
                  <a className="small" href={KEY_URL[k]} target="_blank" rel="noreferrer">Get a key</a>
                  <input type="password" className="onb-key" placeholder="Paste the key" value={key} onChange={e => setKey(e.target.value)} />
                </>}</div>
            </label>))}
          <label className={`choice ${ai === "ollama" ? "on" : ""}`}>
            <input type="radio" name="ai" checked={ai === "ollama"} onChange={() => { setAi("ollama"); setAiMsg(null); }} />
            <div><strong>smith</strong> <span className="muted">(free, fully private)</span>
              <p>Jobsmith's own AI. Runs on this computer, so nothing you write leaves it. Can't search the web.</p>
              {ai === "ollama" && <Smith compact noButton />}</div>
          </label>
          {aiMsg && <p className={aiMsg.ok ? "ok-text" : "warn-text"}>{aiMsg.message}</p>}
          <div className="onb-act">
            <button className="btn primary" onClick={() => saveAi()} disabled={busy || (ai !== "ollama" && !key && !st.ai.detected.some(d => d.kind === ai))}>
              {busy ? <Dots /> : ai === "ollama" ? "Continue" : "Connect"}</button>
            <button className="link" onClick={() => saveAi(true)}>Skip for now</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {cur === "start" && (<>
          <h1>Your first application</h1>
          <p className="muted">Jobsmith fills your best match, then stops and shows you every answer and where it came from. Nothing is sent until you approve it.</p>
          <label className={`choice ${mode === "autopilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "autopilot"} onChange={() => setMode("autopilot")} />
            <div><strong>Then autopilot</strong> <span className="muted">(recommended)</span>
              <p>After you approve the first one, it applies to good matches on its own, within 20 a day and 3 per company a week. Anything it isn't sure about waits for you.</p></div>
          </label>
          <label className={`choice ${mode === "copilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "copilot"} onChange={() => setMode("copilot")} />
            <div><strong>Then copilot</strong><p>It fills every form and stops before Submit. You press it.</p></div>
          </label>
          <p className="small muted">You're responsible for what's sent in your name. Sign-ins, CAPTCHAs and account codes always come to you.</p>
          {msg && <p className="warn-text">{msg}</p>}
          <div className="onb-act">
            <button className="btn primary" onClick={start} disabled={busy}>{busy ? <Dots /> : "Fill my first application"}</button>
            <button className="link" onClick={back}>Back</button>
          </div>
        </>)}

        {step >= 5 && <SmithLine />}
        {cur !== "start" && <p className="onb-skip"><button className="link small" onClick={skipSetup}>Leave setup for now</button>
          <span className="small muted"> · autopilot stays off until you finish</span></p>}
      </div>
    </div>
  );
}
