import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Icon, poll } from "../ui";

type Part = { name: string; cpu: number; memory_mb: number; processes: number };
type Power = {
  battery: { percent: number; plugged: boolean; draining_plugged: boolean; minutes_left: number | null } | null;
  saver: boolean; paused: boolean; mode: string; local_ai_allowed: boolean;
  usage: { parts: Part[]; cpu: number; level: string };
  local_models: { name: string; vram_mb: number }[]; working: number; tabs: number;
};
type S = Record<string, any>;

const LEVEL: Record<string, string> = { low: "Light", medium: "Moderate", high: "Heavy", unknown: "Unknown" };

/** What Jobsmith is doing to your computer right now, and the switches that keep it light. */
export default function Activity() {
  const { refresh } = useContext(StatusCtx);
  const [p, setP] = useState<Power | null>(null);
  const [s, setS] = useState<S | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => { api.get<Power>("/api/power").then(setP).catch(() => {}); };
  useEffect(() => { load(); api.get<S>("/api/settings").then(setS); const t = poll(load, 3000); return () => t.stop(); }, []);
  const save = async (patch: S) => { setS(await api.put<S>("/api/settings", patch)); load(); refresh(); };
  const stop = async () => {
    const r = await api.post<{ stopped: number; unloaded: number }>("/api/stop", { everything: true });
    setMsg(`Stopped ${r.stopped} application${r.stopped === 1 ? "" : "s"}, closed the browser${r.unloaded ? " and unloaded smith" : ""}. Autopilot is off.`);
    load(); refresh();
  };
  if (!p || !s) return <div className="page narrow"><p className="muted">Loading…</p></div>;
  const b = p.battery;
  const max = Math.max(25, ...p.usage.parts.map(x => x.cpu));

  return (
    <div className="page narrow activity">
      <div className="page-h"><div><h1>Activity</h1>
        <p className="muted">What Jobsmith is using on this computer right now.</p></div>
        <button className="btn danger" onClick={stop}><Icon name="x" size={14} />Stop everything</button></div>
      {msg && <p className="note">{msg}</p>}

      <section className="card">
        <div className="energy">
          <div><span className={`lvl lvl-${p.usage.level}`}>{LEVEL[p.usage.level]}</span>
            <p className="muted small">{p.usage.cpu}% of your processor · {p.working} application{p.working === 1 ? "" : "s"} in progress · {p.tabs} browser tab{p.tabs === 1 ? "" : "s"}</p></div>
          {b && <div className="batt"><strong>{b.percent}%</strong>
            <p className="small muted">{b.plugged ? (b.draining_plugged ? "Plugged in, but still draining" : "Plugged in") : `On battery${b.minutes_left ? `, about ${Math.round(b.minutes_left / 60 * 10) / 10} h left` : ""}`}</p></div>}
        </div>
        {b?.draining_plugged && <p className="note warn">Your battery is going down while plugged in: the charger can't keep up. Battery saver is on until it can.</p>}
        <ul className="parts">{p.usage.parts.map(x => (
          <li key={x.name}><span className="pname">{x.name}</span>
            <span className="pbar"><span style={{ width: `${Math.min(100, x.cpu / max * 100)}%` }} /></span>
            <span className="small muted pnum">{x.cpu}% · {x.memory_mb >= 1024 ? `${(x.memory_mb / 1024).toFixed(1)} GB` : `${x.memory_mb} MB`}</span></li>))}</ul>
        {p.local_models.length > 0 && (
          <p className="small">smith is holding {p.local_models.map(m => m.name).join(", ")} in memory
            ({Math.round(p.local_models.reduce((a, m) => a + m.vram_mb, 0) / 1024 * 10) / 10} GB).{" "}
            <button className="link small" onClick={() => api.post("/api/power/unload").then(load)}>Unload it now</button></p>)}
      </section>

      <section className="card">
        <h2>Battery saver {p.saver && <span className="pill-on">on</span>}</h2>
        <p className="small muted">Fills one application at a time, refreshes previews rarely, and keeps smith off. The work just goes slower.</p>
        <div className="seg" role="radiogroup">{([["auto", "When on battery"], ["saver", "Always"], ["full", "Never"]] as [string, string][]).map(([v, l]) => (
          <button key={v} role="radio" aria-checked={s.power_mode === v} className={s.power_mode === v ? "on" : ""} onClick={() => save({ power_mode: v })}>{l}</button>))}</div>
        <h3 className="set-h">On battery</h3>
        <div className="seg" role="radiogroup">{([["slow", "Keep going, one at a time"], ["pause", "Pause autopilot until plugged in"]] as [string, string][]).map(([v, l]) => (
          <button key={v} role="radio" aria-checked={s.on_battery === v} className={s.on_battery === v ? "on" : ""} onClick={() => save({ on_battery: v })}>{l}</button>))}</div>
        <h3 className="set-h">When Gemini's free limit runs out</h3>
        <p className="small muted">smith writes on your own GPU: free and private, but it's the heaviest thing Jobsmith can do.</p>
        <div className="seg" role="radiogroup">{([["plugged", "Use smith when plugged in"], ["always", "Always use smith"], ["never", "Wait for the reset"]] as [string, string][]).map(([v, l]) => (
          <button key={v} role="radio" aria-checked={s.smith_fallback === v} className={s.smith_fallback === v ? "on" : ""} onClick={() => save({ smith_fallback: v })}>{l}</button>))}</div>
      </section>
    </div>
  );
}
