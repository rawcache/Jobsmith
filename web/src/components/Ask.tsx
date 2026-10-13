import { useContext, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Dots } from "../ui";

type Result = { log: string[]; started: string[]; found: number };
const EXAMPLES = ["Apply to NVIDIA hardware internships", "https://github.com/SimplifyJobs/New-Grad-Positions", "Apply to Apple and AMD"];

/** One box for every way to point Jobsmith at jobs: a company, a GitHub list, or links. */
export default function Ask({ onDone }: { onDone?: () => void }) {
  const { refresh } = useContext(StatusCtx);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<string[]>([]);
  const go = async (t = text) => {
    if (!t.trim() || busy) return;
    setBusy(true); setOut([]);
    try {
      const r = await api.post<Result>("/api/command", { text: t.trim() });
      setOut(r.log); setText(""); onDone?.(); refresh();
    } catch (e) { setOut([(e as Error).message]); }
    setBusy(false);
  };
  return (
    <div className="ask">
      <div className="ask-box">
                <input aria-label="Where should Jobsmith apply?" value={text} disabled={busy} onChange={e => setText(e.target.value)}
               onKeyDown={e => e.key === "Enter" && go()} placeholder="Apply to a company, a GitHub job list, or paste job links" />
        <button className="btn primary" onClick={() => go()} disabled={busy || !text.trim()}>{busy ? <Dots /> : "Apply"}</button>
      </div>
      {busy ? <p className="muted small">Finding postings. Searching the web for a company can take a minute.</p> : out.length ? (
        <ul className="ask-out">{out.map((l, i) => <li key={i}>{l}</li>)}</ul>
      ) : (
        <p className="muted small hint-line">Try {EXAMPLES.map((e, i) => <span key={e}><button className="link" onClick={() => setText(e)}>{e.replace("https://github.com/", "")}</button>{i < EXAMPLES.length - 1 ? ", " : "."}</span>)}</p>
      )}
    </div>
  );
}
