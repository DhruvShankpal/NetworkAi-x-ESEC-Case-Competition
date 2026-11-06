import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Suggestion, Suggestions } from "./api";
import { ContribBar } from "./ContribBar";

const REASON_TEXT: Record<string, string> = {
  A1_MO_SIGNATURE: "Same method signature",
  A2_SPACE_TIME: "Close in place and time",
  A3_EVIDENCE_LINK: "Evidence links them",
  R1_MO_MISMATCH: "Method doesn't match",
  R2_TOO_FAR: "Too far apart",
  R3_TIME_GAP: "Too long between them",
  R4_DIFFERENT_TARGET: "Different kind of target",
  D1_NEED_MORE_INFO: "Need more information",
};
type Kind = "accept" | "reject" | "defer";
type Props = {
  sid: string; caseId?: string; pair?: string; ended: boolean;
  onPick: (pairId: string) => void; onSaved: () => void; refreshKey: number;
};
type Load = { state: "loading" } | { state: "error"; msg: string } | { state: "full"; data: Suggestions };

export function DecisionPanel({ sid, caseId, pair, ended, onPick, onSaved, refreshKey }: Props) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!caseId) return;
    let live = true;
    // keep the current card on screen while refetching after a decision (keeps Undo alive)
    setLoad((prev) => (prev.state === "full" && prev.data.case_id === caseId ? prev : { state: "loading" }));
    api.suggestions(sid, caseId)
      .then((data) => live && setLoad({ state: "full", data }))
      .catch((e: ApiError) => live && setLoad({ state: "error", msg: e.message }));
    return () => { live = false; };
  }, [sid, caseId, refreshKey, retry]);

  if (!caseId) {
    return <div className="state"><p>Pick a case from the queue, or click a link in the web, to see its suggested links.</p></div>;
  }
  if (load.state === "loading") {
    return <div className="pane-body" aria-busy="true" aria-label="Loading suggestions">
      {[0, 1, 2].map((i) => <div key={i} className="skeleton tall" />)}</div>;
  }
  if (load.state === "error") {
    return <div className="state error" role="alert"><p className="msg">{load.msg}</p>
      <button className="btn" onClick={() => setRetry((n) => n + 1)}>Retry</button></div>;
  }
  const { data } = load;
  if (!data.suggestions.length) {
    return <div className="state"><p>No other visible case links to {caseId} yet. It stays in the Sleeper queue and is re-scored as new cases arrive.</p></div>;
  }
  const selected = data.suggestions.find((s) => `${s.case_a}__${s.case_b}` === pair) || data.suggestions[0];
  return (
    <div className="pane-body">
      <p className="limits">{data.limits}</p>
      <ul className="list sugg" aria-label={`Suggested links for ${caseId}`}>
        {data.suggestions.map((s) => {
          const id = `${s.case_a}__${s.case_b}`;
          return (
            <li key={id}>
              <SuggestionCard s={s} sid={sid} active={s === selected} onClick={() => onPick(id)} />
            </li>
          );
        })}
      </ul>
      <DecisionCard key={`${selected.case_a}__${selected.case_b}`} sid={sid} caseId={caseId}
        s={selected} reasons={data.reasons} ended={ended} onSaved={onSaved} />
    </div>
  );
}

function SuggestionCard({ s, sid, active, onClick }: { s: Suggestion; sid: string; active: boolean; onClick: () => void }) {
  const shown = useRef(false);
  useEffect(() => {
    if (shown.current) return;
    shown.current = true;
    api.event(sid, "suggestion_shown", { pair: [s.case_a, s.case_b], prob: s.prob, contributions: s.contributions_raw });
  }, [sid, s]);
  const status = s.decision ? { accept: "Accepted", reject: "Rejected", defer: "Deferred" }[s.decision.decision] : "Not decided";
  return (
    <button className="box sugg-item" aria-pressed={active} onClick={onClick}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="mono">{s.other}</span>
        <span className="band num" title={`Model probability ${s.prob.toFixed(3)}`}>{s.band}</span>
      </div>
      <div className="status num">{s.distance_km.toFixed(1)} km · {s.days_apart.toFixed(0)} days · method overlap {s.method_overlap.toFixed(2)}
        {s.other_series ? ` · in ${s.other_series}` : ""} · {status}</div>
    </button>
  );
}

function DecisionCard({ sid, caseId, s, reasons, ended, onSaved }: {
  sid: string; caseId: string; s: Suggestion; reasons: Record<string, string[]>; ended: boolean; onSaved: () => void;
}) {
  const shownAt = useRef(performance.now());
  const clicks = useRef(0);
  const [kind, setKind] = useState<Kind | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ id: string; left: number } | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const options = useMemo(() => (kind ? reasons[kind] : []), [kind, reasons]);
  const question = s.other_series
    ? `Does ${caseId} belong to series ${s.other_series}?`
    : `Are ${caseId} and ${s.other} the same series?`;

  useEffect(() => {
    const count = () => { clicks.current += 1; };
    window.addEventListener("pointerdown", count);
    return () => window.removeEventListener("pointerdown", count);
  }, []);
  useEffect(() => { if (kind) selectRef.current?.focus(); }, [kind]);
  useEffect(() => {
    if (!undo) return;
    if (undo.left <= 0) { setUndo(null); return; }
    const t = setTimeout(() => setUndo((u) => (u ? { ...u, left: u.left - 1 } : u)), 1000);
    return () => clearTimeout(t);
  }, [undo]);

  const save = useCallback(async () => {
    if (!kind) return;
    if (!reason) { setErr("Pick a reason before saving."); selectRef.current?.focus(); return; }
    setSaving(true); setErr(null);
    try {
      const r = await api.decide(sid, {
        case_a: s.case_a, case_b: s.case_b, decision: kind, reason_code: reason,
        clicks: Math.max(1, clicks.current), ms_since_shown: Math.round(performance.now() - shownAt.current),
        prob_shown: s.prob, contributions_shown: s.contributions_raw,
      });
      setUndo({ id: r.decision_id, left: 7 });
      setKind(null); setReason("");
      onSaved();
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  }, [kind, reason, sid, s, onSaved]);

  const doUndo = useCallback(async () => {
    if (!undo) return;
    try { await api.undo(sid, undo.id); setUndo(null); onSaved(); }
    catch (e) { setErr((e as ApiError).message); setUndo(null); }
  }, [undo, sid, onSaved]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || (t.tagName === "SELECT" && !["Enter"].includes(e.key) && !/^[1-6]$/.test(e.key))) return;
      if (ended || e.metaKey || e.ctrlKey || e.altKey) return;
      clicks.current += 1;
      if (!kind && ["1", "2", "3"].includes(e.key)) {
        e.preventDefault(); setKind((["accept", "reject", "defer"] as Kind[])[Number(e.key) - 1]); return;
      }
      if (kind && /^[1-6]$/.test(e.key)) {
        const opt = options[Number(e.key) - 1];
        if (opt) { e.preventDefault(); setReason(opt); }
        return;
      }
      if (kind && e.key === "Enter") { e.preventDefault(); void save(); return; }
      if (kind && e.key === "Escape") { setKind(null); setReason(""); return; }
      if ((e.key === "z" || e.key === "Z") && undo) { e.preventDefault(); void doUndo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [kind, options, save, undo, doUndo, ended]);

  return (
    <section className="box decision" aria-label="Link decision">
      <p className="q">{question}</p>
      <div>
        <span className="band">{s.band}</span>{" "}
        <span className="num" style={{ color: "var(--color-text-muted)" }} title="Model probability (place, time and method only)">
          p = {s.prob.toFixed(2)}</span>
      </div>
      <ul className="reasons">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      {s.dont_fit.length > 0 && (
        <div className="dontfit"><strong>Facts that don’t fit</strong>
          <ul className="reasons">{s.dont_fit.map((r) => <li key={r}>{r}</li>)}</ul></div>
      )}
      <ContribBar items={s.contributions} />
      {s.decision && !undo && (
        <p className="limits">Current decision: {s.decision.decision} ({REASON_TEXT[s.decision.reason_code] || s.decision.reason_code}). Deciding again replaces it.</p>
      )}
      {ended ? <p className="limits">This session has ended. Decisions are read-only.</p> : !kind ? (
        <div className="actions">
          <button className="btn primary" onClick={() => setKind("accept")}><span className="label">Accept</span><span className="kbd">1</span></button>
          <button className="btn" onClick={() => setKind("reject")}><span className="label">Reject</span><span className="kbd">2</span></button>
          <button className="btn" onClick={() => setKind("defer")}><span className="label">Defer</span><span className="kbd">3</span></button>
        </div>
      ) : (
        <form className="decision" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <label htmlFor="reason">Reason for {kind} (required)</label>
          <select id="reason" ref={selectRef} value={reason} aria-invalid={!!err && !reason}
            onChange={(e) => setReason(e.target.value)} aria-describedby={err ? "reason-err" : undefined}>
            <option value="">Choose a reason…</option>
            {options.map((o, i) => <option key={o} value={o}>{i + 1}. {REASON_TEXT[o]}</option>)}
          </select>
          {err && <p id="reason-err" className="field-error" role="alert">{err}</p>}
          <div className="actions">
            <button type="submit" className="btn primary" disabled={saving} data-loading={saving}>
              <span className="label">{saving ? "Saving…" : `Save ${kind}`}</span><span className="kbd">Enter</span></button>
            <button type="button" className="btn quiet" onClick={() => { setKind(null); setReason(""); setErr(null); }}>Cancel</button>
          </div>
        </form>
      )}
      {undo && (
        <div className="undo-bar" role="status"><span>Saved. Undo within <span className="num">{undo.left}</span>s.</span>
          <button className="btn" onClick={() => void doUndo()}>Undo <span className="kbd">Z</span></button></div>
      )}
      {err && !kind && <p className="field-error" role="alert">{err}</p>}
    </section>
  );
}
