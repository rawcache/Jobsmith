import { useEffect, useState } from "react";
import { api } from "../api";
import { Dots } from "../ui";

export type SmithStatus = {
  installed: boolean; running: boolean; remote: boolean; url: string; models: string[]; model: string; has_model: boolean;
  recommended: { model: string; download_gb: number; ram_gb: number; slow: boolean };
  active: boolean; can_install: boolean; engine_gb: number;
  state: { phase: string; message: string; progress: number | null; model: string; error: string };
};

const busy = (p: string) => ["starting", "installing", "downloading"].includes(p);

/** smith: Jobsmith's own AI. One button installs Ollama if needed, downloads the model and switches to it. */
export default function Smith({ onReady, compact, noButton }: { onReady?: () => void; compact?: boolean; noButton?: boolean }) {
  const [st, setSt] = useState<SmithStatus | null>(null);
  const load = () => api.get<SmithStatus>("/api/smith").then(s => { setSt(s); return s; });
  useEffect(() => { load(); }, []);
  const phase = st?.state.phase ?? "idle";
  useEffect(() => {
    if (!busy(phase)) return;
    const t = setInterval(() => load().then(s => { if (s.state.phase === "ready") onReady?.(); }), 700);
    return () => clearInterval(t);
  }, [phase]);
  if (!st) return <p className="muted small"><Dots />Checking this computer</p>;

  const ready = st.active && st.running && st.has_model;
  const rec = st.recommended;
  const go = () => api.post<SmithStatus["state"]>("/api/smith/setup", {}).then(() => load());
  const pct = st.state.progress == null ? null : Math.round(st.state.progress * 100);

  if (ready) return <p className="ok-text small">smith is ready ({st.model}){st.remote ? ` at ${st.url}` : ", running on this computer"}.</p>;
  if (busy(phase)) return (
    <div className="smith-prog">
      <p className="small">{st.state.message || "Getting smith ready"}{pct == null && <Dots />}</p>
      <div className="meter"><span style={{ width: `${pct ?? 5}%` }} /></div>
      {!compact && <p className="small muted">You can keep going. smith finishes in the background.</p>}
    </div>
  );
  const downloads = [
    !st.installed && `Ollama, the free engine smith runs on (about ${st.engine_gb} GB, no admin needed)`,
    !st.has_model && `${st.model}, a ${rec.download_gb} GB model picked for your ${rec.ram_gb} GB of memory`,
  ].filter(Boolean) as string[];
  return (
    <div className="smith">
      {phase === "error" && <p className="warn-text small">{st.state.message}</p>}
      {downloads.length > 0 && !st.remote && (<>
        <p className="small">smith downloads, once:</p>
        <ul className="small">{downloads.map(d => <li key={d}>{d}</li>)}</ul>
      </>)}
      {rec.slow && <p className="small muted">With {rec.ram_gb} GB of memory smith works, but slowly. An API key is faster if you have one.</p>}
      {!st.installed && !st.can_install
        ? <p className="small">Install Ollama from <a href="https://ollama.com" target="_blank" rel="noreferrer">ollama.com</a>, then try again.</p>
        : !noButton && <button className="btn primary sm" onClick={go}>{phase === "error" ? "Try again" : downloads.length ? "Set up smith" : "Use smith"}</button>}
    </div>
  );
}

/** One line for the rest of setup: smith's download progress, or what went wrong with a retry. */
export function SmithLine() {
  const [st, setSt] = useState<SmithStatus["state"] | null>(null);
  const load = () => api.get<SmithStatus>("/api/smith").then(s => setSt(s.state));
  useEffect(() => { load(); }, []);
  const working = !!st && busy(st.phase);
  useEffect(() => { if (!working) return; const t = setInterval(load, 1500); return () => clearInterval(t); }, [working]);
  if (!st || st.phase === "idle") return null;
  const pct = st.progress == null ? null : Math.round(st.progress * 100);
  return (
    <div className="smith-line small">
      {busy(st.phase) && <><span>{st.message || "Getting smith ready"}</span><div className="meter"><span style={{ width: `${pct ?? 5}%` }} /></div></>}
      {st.phase === "ready" && <span className="ok-text">{st.message}</span>}
      {st.phase === "error" && <span className="warn-text">smith: {st.message} <button className="link small" onClick={() => api.post("/api/smith/setup", {}).then(load)}>Try again</button></span>}
    </div>
  );
}
