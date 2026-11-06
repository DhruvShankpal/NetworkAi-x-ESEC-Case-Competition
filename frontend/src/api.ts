// Thin client for the CaseWeb API. Every number shown in the UI comes from these responses.
export type Fact = { field: string; label: string; value: unknown; source: { case_id: string; field: string; spans: number[][] } };
export type CaseDetail = {
  case_id: string; district: string; window: [string, string | null]; reported: string | null;
  lat: number; lon: number; narrative: string; narrative_origin: string | null; extracted_by: string;
  facts: Fact[]; data_label: string;
};
export type Decision = { decision_id: string; decision: "accept" | "reject" | "defer"; reason_code: string };
export type Suggestion = {
  case_a: string; case_b: string; other: string; prob: number; band: string; distance_km: number;
  days_apart: number; method_overlap: number; reasons: string[]; dont_fit: string[];
  contributions: [string, number][]; contributions_raw: Record<string, number>;
  other_series: string | null; decision: Decision | null;
};
export type Suggestions = { case_id: string; suggestions: Suggestion[]; reasons: Record<string, string[]>; limits: string };
export type QueueRow = { case_id: string; district: string; target_type: string | null; reported: string; new_today: boolean; series_id: string | null; woke_today?: boolean };
export type Series = { series_id: string; members: string[]; size: number; status: "candidate" | "active"; strongest: number; first_seen_day: number };
export type Queue = { day: string; series: Series[]; sleeper: QueueRow[]; full: QueueRow[]; counts: Record<string, number> };
export type Session = { session_id: string; analyst: string; day: string; day_number: number; ended: boolean };
export type GraphNode = { id: string; district: string; target_type: string | null; lat: number; lon: number; series_id: string | null; new_today: boolean };
export type GraphEdge = { id: string; source: string; target: string; prob: number; band: string; status: string; distance_km: number; days_apart: number; method_overlap: number };
export type Graph = { day: string; nodes: GraphNode[]; edges: GraphEdge[]; series: Series[]; data_label: string };

export class ApiError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { ...init, headers: { "content-type": "application/json", ...(init?.headers || {}) } });
  } catch {
    throw new ApiError("Can't reach the CaseWeb server. Check that the API is running, then retry.");
  }
  if (!r.ok) {
    let msg = `Request failed (${r.status}).`;
    try { const b = await r.json(); if (typeof b.detail === "string") msg = b.detail; } catch { /* keep default */ }
    throw new ApiError(msg);
  }
  return r.json() as Promise<T>;
}

const base = (sid: string) => `/api/sessions/${encodeURIComponent(sid)}`;
export const api = {
  start: (sid: string, analyst: string) => req<Session>(base(sid), { method: "POST", body: JSON.stringify({ analyst }) }),
  session: (sid: string) => req<Session>(base(sid)),
  setDay: (sid: string, to: string) => req<Session>(`${base(sid)}/day`, { method: "POST", body: JSON.stringify({ to }) }),
  end: (sid: string) => req<{ saved: boolean }>(`${base(sid)}/end`, { method: "POST" }),
  queue: (sid: string) => req<Queue>(`${base(sid)}/queue`),
  caseDetail: (sid: string, id: string) => req<CaseDetail>(`${base(sid)}/cases/${encodeURIComponent(id)}`),
  suggestions: (sid: string, id: string) => req<Suggestions>(`${base(sid)}/cases/${encodeURIComponent(id)}/suggestions`),
  graph: (sid: string, minProb: number, showRejected: boolean) =>
    req<Graph>(`${base(sid)}/graph?min_prob=${minProb}&show_rejected=${showRejected}`),
  decide: (sid: string, body: object) => req<{ decision_id: string; saved_at: string }>(`${base(sid)}/decisions`, { method: "POST", body: JSON.stringify(body) }),
  undo: (sid: string, did: string) => req<{ undone: boolean }>(`${base(sid)}/decisions/${did}/undo`, { method: "POST" }),
  event: (sid: string, event: string, data: object) =>
    req<{ ok: boolean }>(`${base(sid)}/events`, { method: "POST", body: JSON.stringify({ event, data }) }).catch(() => undefined),
};

export const pretty = (v: unknown): string => {
  if (v === null || v === undefined) return "Not recorded";
  if (Array.isArray(v)) return v.length ? v.map((x) => String(x).replace(/_/g, " ")).join(", ") : "Not recorded";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v).replace(/_/g, " ");
};
