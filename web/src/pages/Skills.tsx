import { useContext, useEffect, useState } from "react";
import { api } from "../api";
import { StatusCtx } from "../main";
import { Switch } from "../ui";

type Skill = { key: string; name: string; what: string; enabled: boolean; core?: boolean; soon?: boolean; page?: string };

/** The parts of Jobsmith you can switch on or off. */
export default function Skills() {
  const { refresh } = useContext(StatusCtx);
  const [list, setList] = useState<Skill[]>([]);
  useEffect(() => { api.get<Skill[]>("/api/skills").then(setList); }, []);
  const set = async (k: string, on: boolean) => { setList(await api.post<Skill[]>(`/api/skills/${k}`, { enabled: on })); refresh(); };
  return (
    <div className="page narrow">
      <div className="page-h"><div><h1>Skills</h1><p className="muted">Pick the parts of Jobsmith you want. Each one adds a page to the sidebar.</p></div></div>
      <ul className="skill-list">{list.map(s => (
        <li key={s.key} className={`card skill ${s.soon ? "soon" : ""}`}>
          <div className="grow">
            <div className="skill-h"><h2>{s.name}</h2>{s.core && <span className="tag quiet">Always on</span>}{s.soon && <span className="tag quiet">Coming next</span>}</div>
            <p className="small">{s.what}</p>
            {s.enabled && s.page && <a className="small" href={s.page}>Open</a>}
          </div>
          {!s.core && !s.soon && <Switch on={s.enabled} label={s.name} onChange={v => set(s.key, v)} />}
        </li>))}</ul>
    </div>
  );
}
