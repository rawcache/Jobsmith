import { ReactNode, useEffect, useState } from "react";

/* Small shared pieces: icons, company logos, switch, modal. */

const P: Record<string, string> = {
  bolt: "M13 2 3 14h9l-1 8 10-12h-9l1-8z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  ext: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  pin: "M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  star: "M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z",
  plus: "M12 5v14M5 12h14",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  back: "M15 18l-6-6 6-6",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 6l-10 7L2 6",
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  list: "M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01",
  sliders: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  building: "M3 21h18M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M15 9h3a2 2 0 0 1 2 2v10M9 7h2M9 11h2M9 15h2",
  down: "M6 9l6 6 6-6",
  dollar: "M12 2v20M17 6.5C17 4.6 14.8 3.5 12 3.5S7 4.7 7 6.8c0 4.8 10 2.7 10 7.9 0 2.2-2.3 3.8-5 3.8s-5-1.2-5-3.3",
  level: "M3 20h4v-5H3zM10 20h4V9h-4zM17 20h4V4h-4z",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20",
  passport: "M6 2h12a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM9 17h6",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  collapse: "M4 4h16v16H4zM9 4v16M16 9l-3 3 3 3",
  expand: "M4 4h16v16H4zM9 4v16M13 9l3 3-3 3",
  bell: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  table: "M3 5h18v14H3zM3 10h18M3 15h18M9 5v14",
  board: "M4 4h5v16H4zM10 4h5v10h-5zM16 4h4v13h-4z",
};

export function Icon({ name, size = 16, className = "" }: { name: string; size?: number; className?: string }) {
  if (name === "anvil") return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M2 6.5h14.5c2.6 0 4.6 1.3 5.5 3.3-.3.2-.7.2-1 .2h-4.3c-.9 0-1.7.8-1.7 1.7v.6c0 1 .5 1.9 1.3 2.4l.7.4V17H7v-1.9l.7-.4A2.8 2.8 0 0 0 9 12.3V12H7.2C4.5 12 2.4 9.7 2 7z" />
      <rect x="5" y="18.5" width="14" height="2.5" rx=".6" /></svg>);
  if (name === "github") return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M12 .5a11.5 11.5 0 0 0-3.6 22.4c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 12 .5z" /></svg>);
  if (name === "linkedin") return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M20.4 20.5h-3.6v-5.6c0-1.3 0-3-1.8-3s-2.1 1.4-2.1 2.9v5.7H9.3V9h3.4v1.6c.5-.9 1.6-1.8 3.4-1.8 3.6 0 4.3 2.4 4.3 5.5v6.2zM5.3 7.4a2.1 2.1 0 1 1 0-4.2 2.1 2.1 0 0 1 0 4.2zM7.1 20.5H3.5V9h3.6v11.5z" /></svg>);
  if (name === "devpost") return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="currentColor">
      <path d="M6 1 0 12l6 11h12l6-11L18 1H6zm2.4 5.3h3.7c3.5 0 5.6 2.2 5.6 5.7s-2.1 5.7-5.6 5.7H8.4V6.3zm2.5 2.2v6.9h1.2c2.1 0 3.1-1.3 3.1-3.4s-1-3.5-3.2-3.5h-1.1z" /></svg>);
  return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none"
         stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d={P[name] ?? ""} /></svg>
  );
}

/** Company logo: the site's favicon when we can guess the domain, else the initial on a plain tile. */
export function Logo({ name, size = 40, domain }: { name: string; size?: number; domain?: string }) {
  const d = domain ?? `${name.toLowerCase().replace(/&/g, "and").replace(/\b(inc|llc|corp|corporation|co|ltd|technologies)\b\.?/g, "").replace(/[^a-z0-9]/g, "")}.com`;
  const [failed, setFailed] = useState(false);
  return (
    <span className="logo" style={{ width: size, height: size }} aria-hidden>
      {!failed && d.length > 4
        ? <img src={`https://www.google.com/s2/favicons?domain=${d}&sz=128`} alt="" onError={() => setFailed(true)}
               onLoad={e => { if ((e.target as HTMLImageElement).naturalWidth <= 16) setFailed(true); }} />
        : <b style={{ fontSize: size * 0.42 }}>{(name.match(/[A-Za-z0-9]/)?.[0] ?? "?").toUpperCase()}</b>}
    </span>
  );
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} className={`switch ${on ? "on" : ""}`} onClick={() => onChange(!on)}>
      <span />
    </button>
  );
}

export function Modal({ title, onClose, children, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", k); return () => removeEventListener("keydown", k);
  }, []);
  return (
    <div className="scrim" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal onClick={e => e.stopPropagation()}>
        <header className="modal-h">{title}<button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button></header>
        {children}
      </div>
    </div>
  );
}

export function Dots() { return <span className="dots" aria-label="working"><i /><i /><i /></span>; }

/** setInterval that does nothing while the dashboard tab is hidden, so a forgotten tab costs no battery. */
export function poll(fn: () => void, ms: number) {
  const tick = () => { if (!document.hidden) fn(); };
  const i = setInterval(tick, ms);
  const vis = () => { if (!document.hidden) fn(); };
  document.addEventListener("visibilitychange", vis);
  return { stop: () => { clearInterval(i); document.removeEventListener("visibilitychange", vis); } };
}

export function useTick(ms: number) {
  const [t, setT] = useState(Date.now());
  useEffect(() => { const p = poll(() => setT(Date.now()), ms); return () => p.stop(); }, [ms]);
  return t;
}

/** "8 of 16 skills" in words, coloured only by how good it is. */
export function MatchText({ score, matched, total }: { score: number | null | undefined; matched?: number; total?: number }) {
  if (score == null) return <span className="muted">No posting text yet</span>;
  const tone = score >= 70 ? "good" : score >= 45 ? "fair" : "low";
  return <span className={`match-${tone}`}>{matched != null && total ? `${matched} of ${total} skills` : `${score}% skills match`}</span>;
}


/** Where one application is: five short segments (posting, answers, form, your check, submitted) and a label. */
export function Steps({ p }: { p?: { step: number; total: number; label: string } }) {
  if (!p) return null;
  return (
    <div className="steps-bar" aria-label={`${p.label}, step ${p.step + 1} of ${p.total + 1}`}>
      <div className="segs">{Array.from({ length: p.total + 1 }).map((_, i) => (
        <i key={i} className={i < p.step ? "done" : i === p.step ? (p.step === p.total ? "done" : "now") : ""} />))}</div>
      <span className="small muted">{p.label}</span>
    </div>
  );
}
