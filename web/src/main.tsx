import React, { useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { api } from "./api";
import { poll } from "./ui";
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
import Activity from "./pages/Activity";
import Watch from "./pages/Watch";
import { applyTheme, Palette, TopBar } from "./components/Shell";
import { PixelMark } from "./brand";
import Skills from "./pages/Skills";
import Outreach from "./pages/Outreach";
import Followups from "./pages/Followups";
import Voice from "./pages/Voice";
import Preferences from "./pages/Preferences";

export type Status = {
  llm: { backend: string; ok: boolean; message: string;
         writing: { label: string; ok: boolean; message: string }; research: { label: string; ok: boolean; message: string } };
  auto: { on: boolean; next_run: number | null; last_summary: string }; needs_you: number;
  counts: Record<string, number>; active: Record<string, string>;
  has_resume: boolean; facts: number; autonomy: string; tokens_today: number; live: number; onboarded: boolean; setup_step: string;
  quota: { name: string; used: number; limit: number | null; resets_at: number; limited: boolean; fallback: string | null } | null;
  progress: Record<string, { step: number; total: number; label: string }>;
  attention: { job_id: string; company: string; kind: "code" | "captcha" | "signin"; message: string }[];
  power: { saver: boolean; paused: boolean; battery: { percent: number; plugged: boolean; draining_plugged: boolean } | null };
  setup: { key: string; label: string; done: boolean; detail: string }[];
  me: { first_name: string; last_name: string }; version: string; demo: boolean;
  skills: { key: string; name: string; enabled: boolean }[];
  email: { ready: boolean; address: string; codes: boolean };
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

/** The switch is a real off switch: turning it off stops the applications in progress, not just new ones. */
export async function setAutopilot(on: boolean): Promise<string> {
  const r = await api.post<{ on: boolean; stopped: number }>("/api/autopilot", { on });
  return on ? "Autopilot is on." : r.stopped ? `Autopilot is off. Stopped ${r.stopped} application${r.stopped === 1 ? "" : "s"} in progress.` : "Autopilot is off.";
}

function App() {
  const route = useHash();
  const [status, setStatus] = useState<Status | null>(null);
  // Setup shows on a fresh install and stays up until you finish it, even after the server marks you onboarded.
  const [setup, setSetup] = useState<boolean | null>(null);
  const [toast, setToast] = useState("");
  const refresh = () => api.get<Status>("/api/status").then(s => {
    setStatus(s); setSetup(v => v ?? (!s.onboarded || s.setup_step === "profile" || s.setup_step === "restart"));
  }).catch(() => {});
  const say = (m: string) => { setToast(m); setTimeout(() => setToast(""), 4000); };
  useEffect(() => { refresh(); const t = poll(refresh, 4000); return () => t.stop(); }, []);

  const [view, ...rest] = route.split("/").filter(Boolean);
  const arg = rest.length ? decodeURIComponent(rest.join("/")) : undefined;
  const cur = view === "job" ? "matches" : view === "company" ? "companies" : view ?? "";
  const on = autopilotOn(status);

  return (
    <StatusCtx.Provider value={{ status, refresh }}>
      {setup || view === "setup" ? (<>
        <header className="setup-bar"><span className="rail-brand"><PixelMark size={22} /><span className="wordmark">jobsmith</span></span>
          {status?.demo && <span className="demo-pill">Practice copy</span>}
          {view === "setup" && status?.onboarded && <a className="small" href="#/" onClick={() => setSetup(false)}>Leave setup</a>}</header>
        <Onboarding start={view === "setup" && arg ? Math.max(0, Number(arg) - 1) : undefined}
          onDone={() => { setSetup(false); refresh(); location.hash = "#/"; }} />
      </>) : (
      <div className="shell top">
        <div className="content">
          <TopBar view={view ?? ""} status={status} onToast={say} />
          {status?.demo && <p className="demo-band">Practice copy: a made-up person and made-up jobs. Nothing here opens a real site or sends anything.</p>}
          <main className="wrap">
            {view === "matches" ? <Matches selected={arg} /> :
             view === "job" && arg ? <JobPage id={arg} /> :
             view === "company" && arg ? <Company name={arg} /> :
             view === "companies" ? <Companies /> :
             view === "tracker" ? <Tracker /> :
             view === "documents" ? <Documents /> :
             view === "profile" ? <Profile /> :
             view === "settings" ? <Settings focus={arg} /> :
             view === "preferences" ? <Preferences /> :
             view === "skills" ? <Skills /> :
             view === "outreach" ? <Outreach company={arg} /> :
             view === "followups" ? <Followups /> :
             view === "voice" ? <Voice /> :
             view === "stats" ? <Stats /> :
             view === "activity" ? <Activity /> :
             view === "watch" && arg ? <Watch id={arg} /> : <Home />}
          </main>
        </div>
        <Palette />
      </div>)}
      {toast && <p className="toast floating" role="status">{toast}</p>}
    </StatusCtx.Provider>
  );
}

applyTheme();
createRoot(document.getElementById("root")!).render(<App />);
