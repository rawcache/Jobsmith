import { useEffect, useState } from "react";
import { api } from "../api";

type Field = { field: string; label: string; qtype: string; answer: string; source: string; source_label: string;
  detail: { ref: string; text: string }[]; approved: boolean; kind_check: string; issues: string[]; traces: boolean };
type Submission = { run_id: number; submitted_at: number; confirmed: boolean; sent_by: string; basis: string; note: string;
  fields: Field[]; untraced: number };

// What each submission sent, field by field, and where every answer came from. Written when it was sent, so
// later edits don't change it.
export default function AuditTrail({ id, refresh }: { id: string; refresh?: unknown }) {
  const [subs, setSubs] = useState<Submission[] | null>(null);
  useEffect(() => {
    api.get<{ submissions: Submission[] }>(`/api/jobs/${id}/audit`).then(r => setSubs(r.submissions)).catch(() => setSubs([]));
  }, [id, refresh]);
  if (!subs || subs.length === 0) return null;
  return (
    <section className="block audit">
      <div className="sub-h"><h3>What was sent</h3>
        <a className="link small" href={`/api/jobs/${id}/audit.json`} download>Export as JSON</a></div>
      {subs.map((s, i) => (
        <details key={s.run_id} open={i === 0}>
          <summary>
            {new Date(s.submitted_at * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
            {s.sent_by === "autopilot" ? ", sent by autopilot" : ", sent by you"}
            {s.confirmed ? "" : ", no confirmation page seen"}.{" "}
            {s.untraced
              ? <span className="bad-text">{s.untraced} answer{s.untraced > 1 ? "s don't" : " doesn't"} trace to you</span>
              : <span className="ok-text">Every answer traces to you</span>}
          </summary>
          {s.note && <p className="small muted">{s.note}</p>}
          {s.fields.length === 0 && <p className="small muted">No answers were recorded for this one.</p>}
          {s.fields.length > 0 && <div className="audit-scroll">
            <table className="audit-t">
              <thead><tr><th scope="col">Field</th><th scope="col">Answer sent</th><th scope="col">Came from</th><th scope="col">Check</th></tr></thead>
              <tbody>{s.fields.map(f => (
                <tr key={f.field}>
                  <th scope="row">{f.label}</th>
                  <td><div className="clamp3">{f.answer || "File"}</div></td>
                  <td><span className={f.traces ? "" : "bad-text"}>{f.source_label}</span>
                    {f.detail.map((d, j) => <div key={j} className="small muted clamp2" title={d.text || d.ref}>
                      {d.ref}{d.text && f.source === "resume" ? `: ${d.text}` : ""}</div>)}
                    {f.approved && f.source !== "you" && <div className="small muted">Approved by you</div>}</td>
                  <td>{f.kind_check === "ok" ? <span className="ok-text">Fits</span> : <span className="warn-text">{f.kind_check}</span>}</td>
                </tr>))}</tbody>
            </table>
          </div>}
        </details>))}
    </section>
  );
}
