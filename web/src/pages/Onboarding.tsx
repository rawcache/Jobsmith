import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Dots, poll } from "../ui";
import Smith, { SmithLine } from "../components/Smith";
import { AsciiSmith } from "../brand";

type Goal = { label: string; terms: string[]; sources: string[] };
type Detected = { kind: string; label: string; models?: string[] };
type Check = { key: string; label: string; required: boolean; value: string; done: boolean };
type State = {
  onboarded: boolean; goals_set: string[]; companies: string[]; goals: Record<string, Goal>; fields: string[];
  categories: string[]; locations: string[]; location_choices: string[]; values_all: string[]; values: string[]; checklist: Check[]; profile_ready: boolean; setup_step: string; autonomy: string;
  ai: { detected: Detected[]; ok: boolean; message: string; using: string; backend: string };
  smith: { has_model: boolean; model: string };
};

const KEYS: [string, string, string][] = [
  ["gemini_api", "Gemini", "Free, writes well, and can research companies on the web. Takes a minute: sign in with Google and create a key."],
  ["anthropic_api", "Claude, with an Anthropic API key", "From console.anthropic.com. Billed per use."],
  ["openai_api", "ChatGPT, with an OpenAI API key", "From platform.openai.com. A ChatGPT subscription doesn't include this."],
];
const KEY_URL: Record<string, string> = { gemini_api: "https://aistudio.google.com/apikey",
  anthropic_api: "https://console.anthropic.com/settings/keys", openai_api: "https://platform.openai.com/api-keys" };
const STEPS = ["What you're applying for", "AI", "Resume and details", "How it applies", "Start"];

/** Fields the resume often misses, asked inline so autopilot has everything. */
const ASK: Record<string, { key: string; label: string; choices?: string[]; placeholder?: string }[]> = {
  name: [{ key: "first_name", label: "Legal first name" }, { key: "last_name", label: "Legal last name" }],
  email: [{ key: "email", label: "Email for applications" }],
  phone: [{ key: "phone", label: "Phone" }],
  links: [{ key: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/…" },
          { key: "github", label: "GitHub", placeholder: "https://github.com/…" },
          { key: "website", label: "Website or portfolio" }],
  work_authorized_us: [{ key: "work_authorized_us", label: "Authorized to work in the US?", choices: ["Yes", "No"] }],
  needs_sponsorship: [{ key: "needs_sponsorship", label: "Need visa sponsorship now or later?", choices: ["Yes", "No"] }],
  graduation_date: [{ key: "graduation_date", label: "Graduation", placeholder: "May 2027" }],
  acknowledge_notices: [{ key: "acknowledge_notices", label: "Forms often ask you to confirm you've read a privacy notice or agree to terms. Answer those for you?", choices: ["Yes", "No"] }],
};

function firstStep(s: State): number {
  if (s.setup_step === "restart") return 0;          // "Run setup again": from the top, with everything prefilled
  if (s.setup_step === "profile") return 2;          // the terminal already asked the first questions
  if (!s.goals_set.length) return 0;
  return s.ai.ok ? 2 : 1;
}

export default function Onboarding({ onDone, start: startAt }: { onDone: () => void; start?: number }) {
  const { refresh } = useContext(StatusCtx);
  const [st, setSt] = useState<State | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [goals, setGoals] = useState<string[]>(["internship"]);
  const [companies, setCompanies] = useState("");
  const [cats, setCats] = useState<string[]>(["Software", "AI/ML/Data", "Hardware"]);
  const [places, setPlaces] = useState<string[] | null>(null);
  const [picks, setValsPicked] = useState<string[] | null>(null);
  const [ai, setAi] = useState("");
  const [key, setKey] = useState("");
  const [aiMsg, setAiMsg] = useState<{ ok: boolean; message: string } | null>(null);
  const [mode, setMode] = useState("autopilot");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [vals, setVals] = useState<Record<string, string>>({});

  const load = () => api.get<State>("/api/onboarding").then(s => {
    setSt(s);
    setStep(cur => cur ?? (startAt != null ? Math.min(startAt, STEPS.length - 1) : firstStep(s)));
    return s;
  });
  useEffect(() => {
    load().then(s => {
      if (s.goals_set.length) setGoals(s.goals_set);
      if (s.companies.length) setCompanies(s.companies.join(", "));
      if (s.categories.length) setCats(s.categories);
      const found = s.ai.detected.find(d => d.kind !== "ollama")?.kind;
      setAi(found || (s.smith.has_model ? "ollama" : "gemini_api"));
    });
  }, []);
  // The resume step updates as files are read (and as the terminal changes things).
  useEffect(() => { if (step !== 2) return; const t = poll(load, 2000); return () => t.stop(); }, [step]);
  if (!st || step == null) return <div className="onb"><p className="muted"><Dots />Loading</p></div>;

  const next = () => { setMsg(""); setStep(s => (s ?? 0) + 1); };
  const where = places ?? st.location_choices;
  const valued = picks ?? st.values ?? [];
  const toggle = (list: string[], v: string, on: boolean) => on ? [...new Set([...list, v])] : list.filter(x => x !== v);
  const saveGoal = async () => {
    setBusy(true);
    await api.post("/api/onboarding/goal", { goals, categories: cats, companies: companies.split(",").map(c => c.trim()).filter(Boolean) });
    await api.post("/api/onboarding/prefs", { locations: where, values: valued });
    setBusy(false); next();
  };
  const saveAi = async () => {
    if (ai === "ollama") { await api.post("/api/smith/setup", {}); refresh(); next(); return; }
    setBusy(true);
    const r = await api.post<{ ok: boolean; message: string }>("/api/onboarding/ai", { kind: ai, key });
    setAiMsg(r); setBusy(false); refresh();
    if (r.ok) next();
  };
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
    await load(); setBusy(false); refresh();
  };
  const saveVals = async () => {
    for (const [k, v] of Object.entries(vals)) if (v.trim()) await api.put(`/api/answers/${k}`, { value: v.trim(), confirmed: true });
    await api.post("/api/answers/confirm-all");
    setVals({});
    await load();
  };
  const finish = async () => { setBusy(true); await api.post("/api/onboarding/finish", { autonomy: mode, final: false }); setBusy(false); refresh(); next(); };
  const start = async () => { setBusy(true); await api.post("/api/onboarding/start"); setBusy(false); refresh(); onDone(); location.hash = "#/"; };
  const firstRun = async () => {
    setBusy(true);
    const r = await api.post<{ ok: boolean; message?: string; job_id?: string }>("/api/onboarding/first-run");
    setBusy(false);
    if (r.ok && r.job_id) { onDone(); location.hash = `#/matches/${r.job_id}`; } else setMsg(r.message ?? "Nothing to try yet.");
  };
  const skip = async () => { await api.post("/api/onboarding/finish", { autonomy: "autopilot" }); refresh(); onDone(); };
  const missing = st.checklist.filter(c => !c.done);
  const pdfMissing = !st.checklist.find(c => c.key === "pdf")?.done;

  return (
    <div className="onb">
      <div className="onb-art" aria-hidden={step > 0}><AsciiSmith reveal={step === 0} />
        <p className="small muted">smith is Jobsmith's own AI. It can run on this computer, so nothing you write has to leave it.</p></div>
      <div className="onb-card">
        <p className="onb-step">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>

        {step === 0 && (<>
          <h1>What are you applying for?</h1>
          <p className="muted">Pick as many as you like. You can change this later.</p>
          {Object.entries(st.goals).map(([k, g]) => (
            <label key={k} className={`choice ${goals.includes(k) ? "on" : ""}`}>
              <input type="checkbox" checked={goals.includes(k)} onChange={e => setGoals(toggle(goals, k, e.target.checked))} />
              <div><strong>{g.label}</strong>
                {k === "targeted" && goals.includes(k) && (
                  <input className="onb-key" placeholder="Companies, separated by commas (e.g. NVIDIA, Ramp, Jane Street)"
                    value={companies} onChange={e => setCompanies(e.target.value)} onClick={e => e.preventDefault()} />)}</div>
            </label>
          ))}
          <h3 className="onb-sub">Which fields?</h3>
          <div className="checks">{st.fields.map(f => (
            <label key={f} className="check"><input type="checkbox" checked={cats.includes(f)}
              onChange={e => setCats(toggle(cats, f, e.target.checked))} />{f}</label>))}</div>
          <h3 className="onb-sub">Where?</h3>
          <div className="chips">
            <button className={`chip ${where.length === 0 ? "on" : ""}`} aria-pressed={where.length === 0} onClick={() => setPlaces([])}>Anywhere in the US</button>
            {st.locations.map(p => { const on = where.includes(p); return (
              <button key={p} className={`chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => setPlaces(on ? where.filter(x => x !== p) : [...where, p])}>{p}</button>); })}
          </div>
          <h3 className="onb-sub">What do you value most? <span className="muted small">Up to 3</span></h3>
          <div className="chips">{(st.values_all ?? []).map(v => { const on = valued.includes(v); return (
            <button key={v} className={`chip ${on ? "on" : ""}`} aria-pressed={on} disabled={!on && valued.length >= 3}
              onClick={() => setValsPicked(on ? valued.filter(x => x !== v) : [...valued, v])}>{v}</button>); })}</div>
          <div className="onb-act"><button className="btn primary" onClick={saveGoal} disabled={busy || !cats.length || !goals.length}>Continue</button></div>
        </>)}

        {step === 1 && (<>
          <h1>Which AI should write your answers?</h1>
          <p className="muted">It writes the open-ended answers. Contact details, work authorization and demographics always come straight from your profile.</p>
          {st.ai.detected.filter(d => d.kind !== "ollama").map(d => (
            <label key={d.kind} className={`choice ${ai === d.kind ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === d.kind} onChange={() => setAi(d.kind)} />
              <div><strong>{d.label}</strong><p>Already set up on this computer.</p></div>
            </label>
          ))}
          {KEYS.filter(([k]) => !st.ai.detected.some(d => d.kind === k)).map(([k, label, hint]) => (
            <label key={k} className={`choice ${ai === k ? "on" : ""}`}>
              <input type="radio" name="ai" checked={ai === k} onChange={() => { setAi(k); setKey(""); setAiMsg(null); }} />
              <div><strong>{label}</strong>{k === "gemini_api" && <span className="muted"> (free, recommended)</span>}<p>{hint}</p>
                {ai === k && <>
                  <a className="small" href={KEY_URL[k]} target="_blank" rel="noreferrer">Get a key</a>
                  <input type="password" className="onb-key" placeholder="Paste the key" value={key} onChange={e => setKey(e.target.value)} />
                </>}</div>
            </label>
          ))}
          <label className={`choice ${ai === "ollama" ? "on" : ""}`}>
            <input type="radio" name="ai" checked={ai === "ollama"} onChange={() => { setAi("ollama"); setAiMsg(null); }} />
            <div><strong>smith</strong> <span className="muted">(free, fully private)</span>
              <p>Jobsmith's own AI. Runs on this computer, so nothing you write leaves it. Can't search the web.</p>
              {ai === "ollama" && <Smith compact noButton />}</div>
          </label>
          {aiMsg && <p className={aiMsg.ok ? "ok-text" : "warn-text"}>{aiMsg.message}</p>}
          <div className="onb-act">
            <button className="btn primary" onClick={saveAi} disabled={busy || (ai !== "ollama" && !key && !st.ai.detected.some(d => d.kind === ai))}>
              {busy ? <Dots /> : ai === "ollama" ? "Continue" : "Connect"}</button>
            <button className="link" onClick={next}>Skip for now</button>
          </div>
        </>)}

        {step === 2 && (<>
          <div className="onb-done" aria-label="Already done">
            {[[0, "What you're applying for", (st.goals_set.map(g => st.goals[g]?.label ?? g).join(", ") || "Not set") +
                (st.categories.length ? ` · ${st.categories.join(", ")}` : "")],
              [1, "AI", st.ai.ok ? `${st.ai.using}, connected` : "Not connected yet"]].map(([i, label, val]) => (
              <div key={i as number} className="onb-done-row">
                <span className={`ck ${st.ai.ok || i === 0 ? "" : "warn"}`} aria-hidden>{st.ai.ok || i === 0 ? "✓" : "!"}</span>
                <span className="grow"><strong>{label as string}</strong> <span className="muted">· {val as string}</span></span>
                <button className="link small" onClick={() => setStep(i as number)}>Edit</button>
              </div>))}
            {st.setup_step === "profile" && <p className="small muted">You answered these in the terminal.</p>}
          </div>
          <h1>Your resume and details</h1>
          <p className="muted">Everything fills itself in from your resume. A LaTeX .tex is read most exactly; the PDF is what employers get, so add both if you have them.</p>
          <label className="drop">
            <input type="file" multiple accept=".tex,.pdf,.docx,.txt,.md" onChange={e => { upload(e.target.files); e.target.value = ""; }} />
            {busy ? <span><Dots />Reading your resume</span> : <span><strong>Choose files</strong> or drop them here</span>}
          </label>
          {msg && <p className="warn-text">{msg}</p>}
          <ul className="checklist">
            {st.checklist.map(c => (
              <li key={c.key} className={c.done ? "done" : c.required ? "need" : ""}>
                <span className="mark">{c.done ? "✓" : "·"}</span>
                <span className="lbl">{c.label}{!c.required && !c.done && <span className="muted"> (optional)</span>}</span>
                <span className="val muted">{c.value}</span>
              </li>))}
          </ul>
          {missing.some(c => ASK[c.key]) && (
            <div className="ask-missing">
              <h3 className="onb-sub">Fill in what's missing</h3>
              {missing.flatMap(c => ASK[c.key] ?? []).map(f => (
                <label key={f.key} className="field">{f.label}
                  {f.choices ? (
                    <select value={vals[f.key] ?? ""} onChange={e => setVals({ ...vals, [f.key]: e.target.value })}>
                      <option value="">Choose</option>{f.choices.map(o => <option key={o}>{o}</option>)}</select>
                  ) : <input value={vals[f.key] ?? ""} placeholder={f.placeholder} onChange={e => setVals({ ...vals, [f.key]: e.target.value })} />}
                </label>))}
              {Object.values(vals).some(v => v.trim()) && <button className="btn sm" onClick={saveVals}>Save</button>}
            </div>
          )}
          {pdfMissing && st.checklist[0].done && <p className="warn-text small">Employers get a PDF. Add the PDF version too.</p>}
          <div className="onb-act">
            <button className="btn primary" disabled={!st.profile_ready}
              onClick={() => api.post("/api/answers/confirm-all").then(() => { load(); next(); })}>
              {st.profile_ready ? "Looks right, continue" : "Add the items marked · to continue"}</button>
            <a className="link" href="#/profile" onClick={onDone}>Edit everything in Profile</a>
          </div>
        </>)}

        {step === 3 && (<>
          <h1>How should Jobsmith apply?</h1>
          <label className={`choice ${mode === "autopilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "autopilot"} onChange={() => setMode("autopilot")} />
            <div><strong>Autopilot</strong> <span className="muted">(recommended)</span>
              <p>Checks your job lists every few hours, applies to good fits on its own, and holds anything it isn't sure about for one click from you.</p></div>
          </label>
          <label className={`choice ${mode === "copilot" ? "on" : ""}`}>
            <input type="radio" checked={mode === "copilot"} onChange={() => setMode("copilot")} />
            <div><strong>Copilot</strong><p>Fills every form and stops before Submit. You press it.</p></div>
          </label>
          <p className="small muted">You're responsible for what's sent in your name. CAPTCHAs, sign-ins and emailed codes always come to you.</p>
          <div className="onb-act"><button className="btn primary" onClick={finish} disabled={busy}>Continue</button></div>
        </>)}

        {step === 4 && (<>
          <h1>{mode === "copilot" ? "Ready to fill your first application" : "Ready to start applying"}</h1>
          <p className="muted">{mode === "copilot"
            ? "Jobsmith fills your best match in a browser window and stops before Submit."
            : "Autopilot applies to your best matches now and keeps going every few hours. You can watch any application being filled, and turn it off anytime."}</p>
          {msg && <p className="warn-text">{msg} Your job lists may still be syncing; try again in a minute.</p>}
          <div className="onb-act">
            {mode === "copilot"
              ? <button className="btn primary" onClick={firstRun} disabled={busy}>{busy ? <Dots /> : "Fill my best match"}</button>
              : <button className="btn primary" onClick={start} disabled={busy}>{busy ? <Dots /> : "Start autopilot"}</button>}
            {mode !== "copilot" && <button className="link" onClick={firstRun} disabled={busy}>Watch one first, without submitting</button>}
            <button className="link" onClick={() => api.post("/api/onboarding/finish", { autonomy: mode }).then(() => { refresh(); onDone(); })}>Not now</button>
          </div>
        </>)}

        {step >= 2 && <SmithLine />}
        {step < 4 && <p className="onb-skip"><button className="link small" onClick={skip}>Skip setup</button></p>}
      </div>
    </div>
  );
}
