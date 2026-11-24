import { useEffect, useState } from "react";
import { api } from "../api";
import { poll } from "../ui";

/** One banner at the top of every page while something about you holds applications back (your AI isn't connected,
 *  your salary range or citizenship is missing...), each with a link straight to where it's fixed. One application's
 *  own problems stay under Needs you on Home. */
type Need = { key: string; text: string; page: string; href: string; waiting: number };

export default function NeedsBanner({ route }: { route: string }) {
  const [rows, setRows] = useState<Need[]>([]);
  useEffect(() => {
    const get = () => api.get<{ blocking: Need[] }>("/api/needs").then(r => setRows(r.blocking)).catch(() => {});
    get(); const t = poll(get, 15000); return () => t.stop();
  }, [route]);
  if (!rows.length) return null;
  const shown = rows.slice(0, 5);
  return (
    <aside className="needs-banner" aria-label="What's holding your applications">
      <div className="needs-in">
        <strong>{rows.length === 1 ? "One thing is holding your applications:" : `${rows.length} things are holding your applications:`}</strong>
        <ul>{shown.map(n => (
          <li key={n.key}><a href={n.href} title={`Fix it on the ${n.page}`}>{n.text}</a>
            {n.waiting > 0 && <span className="needs-n"> ({n.waiting} waiting)</span>}</li>))}
          {rows.length > shown.length && <li><a href="#/">{rows.length - shown.length} more under Needs you</a></li>}
        </ul>
      </div>
    </aside>
  );
}
