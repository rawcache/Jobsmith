import { useState } from "react";
import { api } from "../api";
import { Switch } from "../ui";

type S = Record<string, any>;

/** Your email, read-only: types emailed verification codes in for you and moves replies along.
 *  Gmail (app password), Outlook / Microsoft 365 (sign in with Microsoft), or any other IMAP server. */
export default function EmailCard({ s, save, onMsg }: { s: S; save: (p: S) => Promise<void>; onMsg: (m: string) => void }) {
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [ms, setMs] = useState<{ code?: string; url?: string; message: string; ok: boolean } | null>(null);
  const guess = /\.edu$|outlook\.com$|hotmail\.com$|live\.com$/i.test(s.gmail_address || "") && !s.gmail_app_password ? "outlook" : "gmail";
  const prov: string = s.email_provider || guess;
  const ready = !!s.gmail_address && (prov === "gmail" ? !!s.gmail_app_password
    : prov === "outlook" ? !!(s.ms_signed_in && s.ms_client_id) : !!(s.imap_host && s.imap_password));
  const check = async () => { setBusy(true); setTest(await api.post<{ ok: boolean; message: string }>("/api/email/test")); setBusy(false); };
  const signIn = async () => {
    setMs({ ok: true, message: "Asking Microsoft for a sign-in code…" });
    const r = await api.post<{ ok: boolean; code?: string; url?: string; message: string }>("/api/email/ms/start");
    setMs(r);
    if (!r.ok) return;
    for (let i = 0; i < 180; i++) {
      await new Promise(res => setTimeout(res, 5000));
      const p = await api.post<{ ok: boolean; done: boolean; message: string }>("/api/email/ms/poll");
      if (p.done) { setMs({ ok: p.ok, message: p.message }); onMsg(p.message); await save({}); return; }
    }
  };
  return (
    <section className="card" id="email">
      <div className="card-h"><h2>Email</h2>{ready && <span className="pill-on">connected</span>}</div>
      <p className="small muted">Read-only, on this computer. Nothing is sent, deleted or stored anywhere else.</p>
      <ul className="small benefits">
        <li><strong>Verification codes.</strong> When a form emails you a code after Submit, Jobsmith finds it and types it in.</li>
        <li><strong>Replies.</strong> Confirmations, assessments, interviews, offers and rejections move on your Applications.</li>
      </ul>
      <div className="seg" role="radiogroup" aria-label="Email provider">{([["gmail", "Gmail"], ["outlook", "Outlook / Microsoft 365"], ["imap", "Other"]] as [string, string][]).map(([k, l]) => (
        <button key={k} role="radio" aria-checked={prov === k} className={prov === k ? "on" : ""} onClick={() => save({ email_provider: k })}>{l}</button>))}</div>
      <label className="field">Email address that receives the codes<input defaultValue={s.gmail_address} placeholder={prov === "outlook" ? "you@school.edu" : "you@gmail.com"}
        onBlur={e => save({ gmail_address: e.target.value.trim() })} /></label>
      {prov === "gmail" && (<>
        <label className="field">App password<input type="password" defaultValue={s.gmail_app_password} placeholder="16 letters from Google" onBlur={e => save({ gmail_app_password: e.target.value })} /></label>
        <p className="small muted">A separate 16-letter password Google makes for one app (needs 2-step verification). <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">Make one here</a>; revoke it any time. Your normal password never goes here.</p>
      </>)}
      {prov === "outlook" && (<>
        <label className="field">Microsoft client ID<input defaultValue={s.ms_client_id} placeholder="00000000-0000-0000-0000-000000000000" onBlur={e => save({ ms_client_id: e.target.value.trim() })} /></label>
        <details className="small"><summary>One-time setup: get a client ID (free, about 5 minutes)</summary>
          <ol className="steps-list">
            <li>Open <a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank" rel="noreferrer">Azure portal, App registrations</a> (any Microsoft account works) and choose New registration.</li>
            <li>Name it Jobsmith. Supported accounts: any organizational directory and personal Microsoft accounts. No redirect URI.</li>
            <li>In Authentication, set Allow public client flows to Yes.</li>
            <li>In API permissions, add the delegated permissions <code>IMAP.AccessAsUser.All</code> and <code>offline_access</code>.</li>
            <li>Copy the Application (client) ID here.</li>
          </ol></details>
        <div className="row tight">
          <button className="btn primary sm" disabled={!s.ms_client_id || !s.gmail_address} onClick={signIn}>{s.ms_signed_in ? "Sign in again" : "Sign in with Microsoft"}</button>
          {s.ms_signed_in && <button className="btn ghost sm" onClick={() => api.post("/api/email/ms/signout").then(() => save({}))}>Sign out</button>}
        </div>
        {ms && <div className={`note ${ms.ok ? "" : "warn"}`}>{ms.code
          ? <p>Go to <a href={ms.url} target="_blank" rel="noreferrer">{ms.url}</a> and enter <strong className="mono">{ms.code}</strong>. {ms.message}</p>
          : <p>{ms.message}</p>}</div>}
        <p className="small muted">Jobsmith never sees your Microsoft password. Some schools only allow apps an admin approved; if yours does, Microsoft says so, and forwarding your school mail to Gmail works instead.</p>
      </>)}
      {prov === "imap" && (
        <div className="grid-2 tight">
          <label className="field">IMAP server<input defaultValue={s.imap_host} placeholder="imap.example.com" onBlur={e => save({ imap_host: e.target.value.trim() })} /></label>
          <label className="field">Port<input type="number" defaultValue={s.imap_port || 993} onBlur={e => save({ imap_port: Number(e.target.value) || 993 })} /></label>
          <label className="field">Username<input defaultValue={s.imap_user} placeholder="Usually your email address" onBlur={e => save({ imap_user: e.target.value.trim() })} /></label>
          <label className="field">Password<input type="password" defaultValue={s.imap_password} onBlur={e => save({ imap_password: e.target.value })} /></label>
        </div>)}
      <div className="row tight">
        <button className="btn sm" onClick={check} disabled={!ready || busy}>{busy ? "Checking…" : "Test connection"}</button>
        <button className="btn sm ghost" disabled={!ready} onClick={() => api.post<{ error?: string; checked?: number; new_outcomes?: number }>("/api/outcomes/check")
          .then(r => onMsg(r.error ?? `Read ${r.checked} emails: ${r.new_outcomes} new replies`))}>Check for replies now</button>
        {test && <span className={`small ${test.ok ? "ok-text" : "warn-text"}`}>{test.message}</span>}
      </div>
      {ready && <div className="set-row"><div><strong>Enter emailed codes for me</strong><p>Off: you paste codes yourself, from the bell.</p></div>
        <Switch on={s.gmail_codes !== false} label="Enter emailed codes" onChange={v => save({ gmail_codes: v })} /></div>}
    </section>
  );
}
