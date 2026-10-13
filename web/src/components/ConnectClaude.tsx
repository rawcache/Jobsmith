import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";

type Flow = { state: "idle" | "waiting" | "done" | "error"; url: string | null; message: string };

export default function ConnectClaude({ compact = false }: { compact?: boolean }) {
  const { status, refresh } = useContext(StatusCtx);
  const [flow, setFlow] = useState<Flow>({ state: "idle", url: null, message: "" });
  const [code, setCode] = useState("");

  useEffect(() => {
    if (flow.state !== "waiting") return;
    const t = setInterval(async () => {
      const f = await api.get<Flow>("/api/claude/connect");
      setFlow(f);
      if (f.state === "done") refresh();
    }, 1500);
    return () => clearInterval(t);
  }, [flow.state]);

  if (status?.llm.ok && flow.state !== "done") {
    return compact ? null : <p className="connected"><span className="dot" />Connected to Claude</p>;
  }
  const start = async () => setFlow(await api.post<Flow>("/api/claude/connect"));

  return (
    <div className={`connect ${compact ? "compact" : ""}`}>
      {flow.state === "idle" && (<>
        {!compact && <p>Jobsmith writes your answers with your own Claude subscription. Sign in once and it stays connected.</p>}
        <button className="btn primary" onClick={start}>Connect Claude</button>
      </>)}
      {flow.state === "waiting" && (<>
        <p>{flow.url ? "A Claude sign-in page should have opened in your browser. Approve it there." : flow.message}</p>
        {flow.url && <p><a href={flow.url} target="_blank" rel="noreferrer">Open the sign-in page</a> if it didn't open.</p>}
        {flow.url && (<>
          <label className="code">If the page shows a code, paste it here
            <div className="row">
              <input value={code} onChange={e => setCode(e.target.value)} placeholder="Paste code" />
              <button className="btn primary" disabled={!code.trim()}
                      onClick={async () => { setFlow(await api.post<Flow>("/api/claude/code", { code })); setCode(""); }}>Finish</button>
            </div>
          </label>
        </>)}
        <button className="btn ghost" onClick={async () => setFlow(await api.post<Flow>("/api/claude/cancel"))}>Cancel</button>
      </>)}
      {flow.state === "done" && <p className="connected"><span className="dot" />Connected to Claude</p>}
      {flow.state === "error" && (<>
        <p className="err">{flow.message}</p>
        <button className="btn primary" onClick={start}>Try again</button>
      </>)}
    </div>
  );
}
