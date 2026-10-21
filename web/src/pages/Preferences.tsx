import { useContext, useEffect, useState } from "react";
import { api, VALUES } from "../api";
import { StatusCtx } from "../main";

type S = Record<string, any>;

const GOALS: [string, string, string][] = [
  ["internship", "Internships", "Summer 2027"],
  ["newgrad", "New grad", "Full-time, starting after you graduate"],
  ["targeted", "Specific companies", "Only the ones you name"],
];
const FIELDS = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"];
const TERMS = ["Summer 2027", "Fall 2026", "Spring 2027", "New Grad"];
const PLACES = ["Remote", "New York", "SF Bay Area", "Seattle", "Boston", "Austin", "Atlanta", "Chicago", "Los Angeles",
  "Washington DC area", "Canada", "London and the UK", "Europe", "India", "Singapore", "Asia-Pacific", "Latin America"];
const PICKY: [string, number, string, string][] = [
  ["strong", 60, "Strong fits", "Fewer, better-matched applications"],
  ["good", 40, "Good fits", "The default: a balance"],
  ["any", 20, "Anything I qualify for", "The most applications"],
];

/** Job preferences: what autopilot looks for. Each question is one card, and changes save as you click. */
export default function Preferences() {
  const { refresh } = useContext(StatusCtx);
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState("");
  const load = () => api.get<S>("/api/settings").then(setS);
  useEffect(() => { load(); }, []);
  if (!s) return <div className="page narrow"><p className="muted">Loading…</p></div>;

  const done = (m = "Saved") => { setSaved(m); load(); refresh(); setTimeout(() => setSaved(""), 1600); };
  const mark = () => api.post("/api/onboarding/prefs", {});
  const put = async (patch: S) => { await api.put("/api/settings", patch); await mark(); done(); };
  const toggle = (list: string[], v: string) => list.includes(v) ? list.filter(x => x !== v) : [...list, v];

  const goals: string[] = s.goals ?? [];
  const setGoals = async (next: string[]) => {
    if (!next.length) return;
    await api.post("/api/onboarding/goal", { goals: next, companies: s.target_companies ?? [] }); await mark();
    done(next.some(g => !goals.includes(g)) ? "Saved. Adding the matching job lists." : "Saved");
  };
  const places: string[] = s.location_choices ?? [];
  const setPlaces = async (next: string[]) => { await api.post("/api/onboarding/prefs", { locations: next }); done(); };
  const picky = s.min_fit_score >= 55 ? "strong" : s.min_fit_score <= 25 ? "any" : "good";
  const listOf = (k: string) => (e: { target: { value: string } }) =>
    put({ [k]: e.target.value.split(",").map(x => x.trim()).filter(Boolean) });

  return (
    <div className="page narrow prefs">
      <div className="page-h"><div><h1>Job preferences</h1>
        <p className="muted">{saved || "What autopilot looks for. Changes save as you click."}</p></div></div>

      <section className="card">
        <h2>What are you looking for?</h2>
        <p className="small muted">Pick any.</p>
        <div className="opt-grid">{GOALS.map(([k, label, hint]) => {
          const on = goals.includes(k);
          return (
            <button key={k} className={`opt ${on ? "on" : ""}`} aria-pressed={on} onClick={() => setGoals(toggle(goals, k))}>
              <span className="tick" aria-hidden>{on ? "✓" : ""}</span>
              <span><strong>{label}</strong><span className="small muted">{hint}</span></span>
            </button>);
        })}</div>
        {goals.includes("targeted") && (
          <label className="field">Companies to apply to
            <input defaultValue={(s.target_companies ?? []).join(", ")} onBlur={listOf("target_companies")}
              placeholder="NVIDIA, Jane Street, Apple" /></label>)}
      </section>

      <section className="card">
        <div className="card-h"><h2>What do you value in a role?</h2><span className="small muted num">{(s.values ?? []).length} of 3</span></div>
        <p className="small muted">Autopilot leans toward roles that show these, and your cover letters mention them where they're true.</p>
        <div className="chips">{VALUES.map(v => {
          const vals: string[] = s.values ?? [];
          const on = vals.includes(v);
          const full = !on && vals.length >= 3;
          return (
            <button key={v} className={`chip ${on ? "on" : ""}`} aria-pressed={on} disabled={full}
              onClick={() => api.post("/api/onboarding/prefs", { values: on ? vals.filter(x => x !== v) : [...vals, v] }).then(() => done())}>{v}</button>);
        })}</div>
      </section>

      <section className="card">
        <h2>Which fields?</h2>
        <div className="chips">{FIELDS.map(c => { const on = s.target_categories.includes(c); return (
          <button key={c} className={`chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => put({ target_categories: toggle(s.target_categories, c) })}>{c}</button>); })}</div>
        <h3 className="set-h">Which terms?</h3>
        <div className="chips">{[...new Set([...TERMS, ...s.target_terms])].map((c: string) => { const on = s.target_terms.includes(c); return (
          <button key={c} className={`chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => put({ target_terms: toggle(s.target_terms, c) })}>{c}</button>); })}</div>
      </section>

      <section className="card">
        <h2>Where would you work?</h2>
        <div className="chips">
          <button className={`chip ${places.length === 0 ? "on" : ""}`} aria-pressed={places.length === 0} onClick={() => setPlaces([])}>Anywhere in the US</button>
          {PLACES.map(p => { const on = places.includes(p); return (
            <button key={p} className={`chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => setPlaces(toggle(places, p))}>{p}</button>); })}</div>
      </section>

      <section className="card">
        <h2>How picky should autopilot be?</h2>
        <div className="opt-grid">{PICKY.map(([k, , label, hint]) => (
          <button key={k} className={`opt ${picky === k ? "on" : ""}`} aria-pressed={picky === k}
            onClick={() => api.post("/api/onboarding/prefs", { picky: k }).then(() => done())}>
            <span className="tick round" aria-hidden>{picky === k ? "●" : ""}</span>
            <span><strong>{label}</strong><span className="small muted">{hint}</span></span>
          </button>))}</div>
      </section>

      <section className="card">
        <h2>Companies to skip</h2>
        <label className="field">Never apply to
          <input defaultValue={(s.exclude_companies ?? []).join(", ")} onBlur={listOf("exclude_companies")} placeholder="Company names, separated by commas" /></label>
      </section>
    </div>
  );
}
