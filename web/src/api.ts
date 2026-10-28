export type Job = {
  id: string; company: string; title: string; url: string; ats: string;
  locations: string[]; terms: string[]; category: string; sponsorship: string;
  date_posted: number | null; fit_score: number | null; fit_reasons: string[];
  status: string; verdict: string | null; verdict_note?: string | null; error: string | null;
  description?: string; research?: Research; questions?: unknown[];
  referral_name?: string | null; referral_url?: string | null; outcome?: string | null; tokens?: number;
  match?: number | null; match_hits?: number; match_total?: number; connections?: number; hold_reason?: string | null;
  pay?: string; updated_at?: number; left_out?: string | null;
  eligibility?: { ok?: boolean; reasons?: string[]; notes?: string[] };
  ai_blocked?: boolean;
  gate?: FitGate;
};
export type FitGate = { passed: boolean; score: number | null; threshold: number; summary: string; for: string[]; against: string[] };
export type Research = {
  summary?: string; what_the_team_builds?: string; tech_stack?: string[];
  recent_news?: { headline: string; url: string }[];
  people?: { name: string; role: string; why_relevant?: string; source_url?: string }[];
  talking_points?: string[]; red_flags?: string[];
  fit_angles?: { angle: string; fact_ids?: string[]; source_url?: string }[]; sources?: string[];
  values_and_culture?: string; _by?: string; _reused_from?: string;
};
export type Fact = { id: string; category: string; subject: string; text: string; source: string };
export type Draft = {
  id: number; field: string; label: string; qtype: string; required: number; options: string[];
  kind: string; canon: string | null; answer: string; fact_ids: string[]; rationale: string;
  confidence: number; issues: string[]; verdict: string | null; note: string | null;
  final_answer: string | null; facts: Fact[]; model?: string | null;
};
export type Run = { id: number; kind: string; status: string; log: string; screenshot: string | null; started_at: number };
export type Answer = { key: string; label: string; value: string; confirmed: number };
export type Usage = { calls: number; input: number; output: number; cached: number; searches: number;
  cost: number | null; tokens: number; by_purpose?: { purpose: string; tokens: number; cached: number; searches: number; cost: number | null }[] };
export type LiveTab = { job_id: string; company: string; title: string; phase: string; phase_label: string;
  note: string; needs_code: boolean; url: string; since: number };
export type Person = { first_name: string; last_name: string; url: string; company: string; position: string; connected_on: string };
export type Match = { score: number | null; matched: string[]; missing: string[]; total: number; label?: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* keep statusText */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export const api = {
  get: <T,>(p: string) => req<T>(p),
  post: <T,>(p: string, body?: unknown) =>
    req<T>(p, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  put: <T,>(p: string, body: unknown) => req<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  del: <T,>(p: string) => req<T>(p, { method: "DELETE" }),
};

export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  const d = s / 86400;
  if (d < 2) return "yesterday";
  if (d < 30) return `${Math.floor(d)}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

export function tok(n: number | null | undefined): string {
  if (!n) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export const STATUS_LABEL: Record<string, string> = {
  new: "Matched", fetched: "Matched", drafted: "Drafted", filling: "Applying", filled: "Needs one click",
  submitted: "Applied", skipped: "Skipped", error: "Needs you",
};
export const OUTCOME_LABEL: Record<string, string> = {
  received: "Received", rejected: "Rejected", assessment: "Assessment", interview: "Interview", offer: "Offer",
};
export const companyHref = (c: string) => `#/company/${encodeURIComponent(c)}`;

/** What you value in a role (same list as match.VALUES on the engine). Up to 3. */
export const VALUES = ["Learning and mentorship", "Hard technical problems", "Impact on real users", "Pay", "Well-known company",
  "Small team, big ownership", "Path to a full-time offer", "Work-life balance", "A mission I care about", "Remote or flexible"];
