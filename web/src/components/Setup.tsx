import { useContext } from "react";
import { StatusCtx } from "../main";
import { Icon } from "../ui";
import ConnectClaude from "./ConnectClaude";

const LINK: Record<string, string> = { claude: "#/settings", resume: "#/profile", pdf: "#/profile", answers: "#/profile", jobs: "#/settings" };

export default function Setup() {
  const { status } = useContext(StatusCtx);
  if (!status || status.setup.every(s => s.done)) return null;
  const next = status.setup.find(s => !s.done)!;
  const done = status.setup.filter(s => s.done).length;
  return (
    <section className="card setup" aria-label="Finish setting up">
      <div className="card-h">
        <h2>Finish setting up</h2>
        <span className="muted small">{done} of {status.setup.length} done</span>
      </div>
      <ol>
        {status.setup.map(s => (
          <li key={s.key} className={s.done ? "done" : s === next ? "next" : ""}>
            <span className="tick">{s.done ? <Icon name="check" size={14} /> : null}</span>
            <div>
              {LINK[s.key] && !s.done ? <a href={LINK[s.key]}>{s.label}</a> : <span>{s.label}</span>}
              <span className="muted small"> {s.done && s.key === "claude" ? "Connected" : s.detail}</span>
              {s === next && s.key === "claude" && status.llm.backend === "claude_cli" && <ConnectClaude compact />}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
