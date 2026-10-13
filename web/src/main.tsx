import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { api } from "./api";
import { Icon, Switch } from "./ui";
import Home from "./pages/Home";
import Matches from "./pages/Matches";
import JobPage from "./pages/JobDetail";
import Company from "./pages/Company";
import Companies from "./pages/Companies";
import Tracker from "./pages/Tracker";
import Documents from "./pages/Documents";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import Stats from "./pages/Stats";
import Onboarding from "./pages/Onboarding";

export type Status = {
  llm: { backend: string; ok: boolean; message: string;
         writing: { label: string; ok: boolean; message: string }; research: { label: string; ok: boolean; message: string } };
  auto: { on: boolean; next_run: number | null; last_summary: string }; needs_you: number;
  counts: Record<string, number>; active: Record<string, string>;
  has_resume: boolean; facts: number; autonomy: string; tokens_today: number; live: number; onboarded: boolean;
  setup: { key: string; label: string; done: boolean; detail: string }[];
};

function useHash() {
  const [h, setH] = useState(location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => { setH(location.hash.slice(1) || "/"); scrollTo(0, 0); };
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return h;
}

export const StatusCtx = React.createContext<{ status: Status | null; refresh: () => void }>({
  status: null, refresh: () => {},
});

export const autopilotOn = (s: Status | null) => !!s && s.autonomy !== "copilot" && s.auto.on;

export async function setAutopilot(on: boolean) {
  await api.put("/api/settings", on ? { autonomy: "autopilot", auto_run: true } : { autonomy: "copilot", auto_run: false });
}

const NAV: [string, string][] = [["", "Autopilot"], ["matches", "Matches"], ["tracker", "Tracker"],
  ["companies", "Companies"], ["documents", "Documents"], ["profile", "Profile"]];

function App() {
  const route = useHash();
  const [status, setStatus] = useState<Status | null>(null);
  const [setupDone, setSetupDone] = useState(false);
  const refresh = () => api.get<Status>("/api/status").then(setStatus).catch(() => {});
  useEffect(() => { refresh(); const t = setInterval(refresh, 4000); return () => clearInterval(t); }, []);

  const [view, ...rest] = route.split("/").filter(Boolean);
  const arg = rest.length ? decodeURIComponent(rest.join("/")) : undefined;
  const cur = view === "job" ? "matches" : view === "company" ? "companies" : view ?? "";
  const on = autopilotOn(status);
  const w = status?.llm.writing;

  return (
    <StatusCtx.Provider value={{ status, refresh }}>
      {status && !status.onboarded && !setupDone ? (
        <header className="nav"><span className="brand">Jobsmith</span></header>
      ) : <header className="nav">
        <a href="#/" className="brand" aria-label="Jobsmith home">
Jobsmith
        </a>
        <nav aria-label="Main">
          {NAV.map(([k, label]) => (
            <a key={k} href={`#/${k}`} aria-current={cur === k ? "page" : undefined}>
              {label}{k === "tracker" && status && status.needs_you > 0 && <span className="nav-n">{status.needs_you}</span>}
            </a>
          ))}
        </nav>
        <div className="nav-r">
          {w && (
            <a href="#/settings" className={`ai-chip ${w.ok ? "ok" : "warn"}`} title={w.ok ? `Writing with ${w.label}` : w.message}>
              <span className="dot" />{w.ok ? w.label.replace(/ \((.*)\)/, ", $1") : w.message.startsWith("smith is getting") ? w.message : "Connect your AI"}
            </a>
          )}
          {status && (
            <label className={`ap-toggle ${on ? "on" : ""}`}>
              <span>Autopilot</span>
              <Switch on={on} label="Autopilot" onChange={v => setAutopilot(v).then(refresh)} />
            </label>
          )}
          <a href="#/settings" className="icon-btn" aria-label="Settings" aria-current={cur === "settings" ? "page" : undefined}><Icon name="gear" size={18} /></a>
        </div>
      </header>}
      {status && !status.onboarded && !setupDone ? <Onboarding onDone={() => { setSetupDone(true); refresh(); }} /> :
      <main className="wrap">
        {view === "matches" ? <Matches selected={arg} /> :
         view === "job" && arg ? <JobPage id={arg} /> :
         view === "company" && arg ? <Company name={arg} /> :
         view === "companies" ? <Companies /> :
         view === "tracker" ? <Tracker /> :
         view === "documents" ? <Documents /> :
         view === "profile" ? <Profile /> :
         view === "settings" ? <Settings /> :
         view === "stats" ? <Stats /> : <Home />}
      </main>}
    </StatusCtx.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
