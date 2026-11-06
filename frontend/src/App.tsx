import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, pretty } from "./api";
import type { CaseDetail, Graph, Queue, Session } from "./api";
import { DecisionPanel } from "./DecisionPanel";
import { MapView } from "./MapView";
import { useUrlState } from "./urlState";
import type { View } from "./urlState";
import { WebGraph } from "./WebGraph";

type Load<T> = { state: "loading" } | { state: "error"; msg: string } | { state: "full"; data: T };
const addDays = (d: string, n: number) => {
  const t = new Date(`${d}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10);
};

export default function App() {
  const [url, setUrl] = useUrlState();
  const [session, setSession] = useState<Load<Session>>({ state: "loading" });
  const [queue, setQueue] = useState<Load<Queue>>({ state: "loading" });
  const [graph, setGraph] = useState<Load<Graph>>({ state: "loading" });
  const [tick, setTick] = useState(0);          // bump to refetch after a decision or day change
  const [busyDay, setBusyDay] = useState(false);
  const [dayErr, setDayErr] = useState<string | null>(null);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [ended, setEnded] = useState(false);

  // Start or resume the session; honour a day in the URL if the server allows it.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        let s = await api.start(url.s, url.analyst); // idempotent: resumes an existing session
        if (url.day && url.day !== s.day) s = await api.setDay(url.s, url.day).catch(() => s);
        if (live) { setSession({ state: "full", data: s }); setEnded(s.ended); setUrl({ day: s.day }); }
      } catch (e) {
        if (live) setSession({ state: "error", msg: (e as ApiError).message });
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url.s]);

  const day = session.state === "full" ? session.data.day : undefined;
  useEffect(() => {
    if (!day) return;
    let live = true;
    setQueue((q) => (q.state === "full" ? q : { state: "loading" }));
    api.queue(url.s).then((d) => live && setQueue({ state: "full", data: d }))
      .catch((e: ApiError) => live && setQueue({ state: "error", msg: e.message }));
    return () => { live = false; };
  }, [url.s, day, tick]);
  useEffect(() => {
    if (!day) return;
    let live = true;
    api.graph(url.s, url.min, url.rej).then((d) => live && setGraph({ state: "full", data: d }))
      .catch((e: ApiError) => live && setGraph({ state: "error", msg: e.message }));
    return () => { live = false; };
  }, [url.s, day, tick, url.min, url.rej]);

  const moveDay = async (n: number) => {
    if (!day) return;
    setBusyDay(true); setDayErr(null);
    try {
      const s = await api.setDay(url.s, addDays(day, n));
      setSession({ state: "full", data: s }); setUrl({ day: s.day });
    } catch (e) { setDayErr((e as ApiError).message); }
    finally { setBusyDay(false); }
  };

  const pickCase = useCallback((id: string) => setUrl({ case: id, pair: undefined }), [setUrl]);
  const pickPair = useCallback((pairId: string, caseId: string) => setUrl({ case: caseId, pair: pairId }), [setUrl]);
  const setView = (v: View) => { setUrl({ view: v }); api.event(url.s, "view_changed", { view: v }); };
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  if (session.state === "error") {
    return <div className="state error" role="alert"><p className="msg">{session.msg}</p>
      <button className="btn" onClick={() => window.location.reload()}>Retry</button></div>;
  }
  if (ended && confirmEnd === false && session.state === "full" && session.data.ended) {
    return <div className="saved" role="status">Session saved. A teammate will run the scorer.</div>;
  }
  const s = session.state === "full" ? session.data : null;

  return (
    <div className="shell">
      <header className="topbar">
        <h1 className="brand">CaseWeb <span>· Replay</span></h1>
        <div className="day" aria-live="polite">
          {s ? <span className="num">Day {s.day_number} · {s.day} (shifted)</span> : <span className="skeleton" style={{ width: 180 }} />}
          <button className="btn" aria-label="Previous day" disabled={!s || busyDay || s.day_number <= 1 || ended}
            onClick={() => moveDay(-1)}>‹</button>
          <button className="btn primary" disabled={!s || busyDay || ended} data-loading={busyDay} onClick={() => moveDay(1)}>
            <span className="label">{busyDay ? "Loading day…" : "Advance day ›"}</span></button>
        </div>
        {dayErr && <span className="field-error" role="alert">{dayErr}</span>}
        <span className="tag">Synthetic data</span>
        <div className="spacer" />
        <span className="meta">Session {url.s} · Analyst {s?.analyst ?? url.analyst}</span>
        <button className="btn" disabled={!s || ended} onClick={() => setConfirmEnd(true)}>End session</button>
      </header>

      <main className="workbench">
        <nav className="pane" aria-label="Case queue">
          <div className="pane-head"><h2>Queue</h2></div>
          <QueuePane q={queue} tab={url.tab} selected={url.case} onTab={(t) => setUrl({ tab: t })} onPick={pickCase}
            onRetry={refresh} />
        </nav>

        <section className="pane center" aria-label="Case and links">
          <div className="center-top">
            <CasePane sid={url.s} caseId={url.case} refreshKey={tick} />
          </div>
          <div style={{ display: "grid", gridTemplateRows: "auto minmax(0,1fr)", minHeight: 0 }}>
            <div className="viewbar" role="toolbar" aria-label="Links view">
              <div role="tablist" aria-label="View" style={{ display: "flex", gap: 4 }}>
                {(["web", "map", "table"] as View[]).map((v) => (
                  <button key={v} role="tab" className="tab" aria-selected={url.view === v} onClick={() => setView(v)}>
                    {{ web: "Web of cases", map: "Map", table: "Table" }[v]}</button>
                ))}
              </div>
              <label htmlFor="min">Show links from
                <input id="min" type="range" min={0.1} max={0.9} step={0.05} value={url.min}
                  onChange={(e) => setUrl({ min: Number(e.target.value) })} aria-valuetext={`probability ${url.min}`} />
                <span className="num">p ≥ {url.min.toFixed(2)}</span></label>
              <label><input type="checkbox" checked={url.rej} onChange={(e) => setUrl({ rej: e.target.checked })} /> Show rejected</label>
            </div>
            <div className="canvas">
              <LinksView g={graph} view={url.view} selectedCase={url.case} selectedPair={url.pair}
                onCase={pickCase} onPair={pickPair} onRetry={refresh} />
            </div>
          </div>
        </section>

        <aside className="pane" aria-label="Link suggestions">
          <div className="pane-head"><h2>Link suggestions{url.case ? <> for <span className="mono">{url.case}</span></> : ""}</h2></div>
          <DecisionPanel sid={url.s} caseId={url.case} pair={url.pair} ended={ended}
            onPick={(p) => setUrl({ pair: p })} onSaved={refresh} refreshKey={tick} />
        </aside>
      </main>

      {confirmEnd && (
        <div className="dialog-scrim" role="dialog" aria-modal="true" aria-labelledby="end-title">
          <div className="box dialog">
            <h2 id="end-title">End this session?</h2>
            <p>Your decisions are saved. After ending, the session is read-only and a teammate runs the scorer.</p>
            <div className="actions">
              <button className="btn primary" autoFocus onClick={async () => {
                await api.end(url.s); setEnded(true); setConfirmEnd(false);
                setSession((x) => (x.state === "full" ? { state: "full", data: { ...x.data, ended: true } } : x));
              }}>End session</button>
              <button className="btn" onClick={() => setConfirmEnd(false)}>Keep working</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function QueuePane({ q, tab, selected, onTab, onPick, onRetry }: {
  q: Load<Queue>; tab: "series" | "sleeper" | "full"; selected?: string;
  onTab: (t: "series" | "sleeper" | "full") => void; onPick: (id: string) => void; onRetry: () => void;
}) {
  return (
    <>
      <div className="tabs" role="tablist" aria-label="Queue">
        {(["series", "sleeper", "full"] as const).map((t) => (
          <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => onTab(t)}>
            {{ series: "Series", sleeper: "Sleeper", full: "Full" }[t]}
            {q.state === "full" && <span className="num"> {t === "series" ? q.data.counts.series : t === "sleeper" ? q.data.counts.sleeper : q.data.counts.visible_cases}</span>}
          </button>
        ))}
      </div>
      <div className="pane-body">
        {q.state === "loading" && <div aria-busy="true" aria-label="Loading queue">{[...Array(8)].map((_, i) => <div key={i} className="skeleton" style={{ margin: "10px 0" }} />)}</div>}
        {q.state === "error" && <div className="state error" role="alert"><p className="msg">{q.msg}</p><button className="btn" onClick={onRetry}>Retry</button></div>}
        {q.state === "full" && tab === "series" && (q.data.series.length === 0
          ? <div className="state"><p>No series yet. Series appear when two visible cases link strongly. Advance a day to bring in new cases.</p></div>
          : <ul className="list">{q.data.series.map((s) => (
            <li key={s.series_id}><button className="row" aria-current={s.members.includes(selected || "")} onClick={() => onPick(s.members[0])}>
              <span><strong>{s.series_id}</strong> <span className="num">({s.size})</span></span>
              <span className="tag">{s.status === "active" ? "Active" : "Candidate"}</span>
              <span className="sub num">Strongest link p = {s.strongest.toFixed(2)} · first seen day {s.first_seen_day}</span>
            </button></li>))}</ul>)}
        {q.state === "full" && tab !== "series" && ((tab === "sleeper" ? q.data.sleeper : q.data.full).length === 0
          ? <div className="state"><p>{tab === "sleeper" ? "No sleeper cases. Every visible case has at least one suggested link." : "No cases are visible yet. Advance a day."}</p></div>
          : <ul className="list">{(tab === "sleeper" ? q.data.sleeper : q.data.full).map((r) => (
            <li key={r.case_id}><button className="row" aria-current={r.case_id === selected} onClick={() => onPick(r.case_id)}>
              <span className="mono">{r.case_id}</span>
              <span>{r.woke_today ? <span title="Linked today for the first time"><span className="marker" /> Woke</span> : r.new_today ? <span className="tag">New</span> : null}</span>
              <span className="sub num">District {r.district} · {pretty(r.target_type)} · reported {r.reported}{r.series_id ? ` · ${r.series_id}` : ""}</span>
            </button></li>))}</ul>)}
      </div>
    </>
  );
}

function CasePane({ sid, caseId, refreshKey }: { sid: string; caseId?: string; refreshKey: number }) {
  const [c, setC] = useState<Load<CaseDetail>>({ state: "loading" });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!caseId) return;
    let live = true;
    setC({ state: "loading" });
    api.caseDetail(sid, caseId).then((d) => live && setC({ state: "full", data: d }))
      .catch((e: ApiError) => live && setC({ state: "error", msg: e.message }));
    return () => { live = false; };
  }, [sid, caseId, refreshKey, retry]);
  const marked = useMemo(() => (c.state === "full" ? markSpans(c.data) : null), [c]);
  if (!caseId) return <div className="state"><p>Pick a case from the queue to see its facts, their sources and its suggested links.</p></div>;
  if (c.state === "loading") return <div className="pane-body" aria-busy="true" aria-label="Loading case" style={{ paddingTop: 16 }}>{[...Array(6)].map((_, i) => <div key={i} className="skeleton" />)}</div>;
  if (c.state === "error") return <div className="state error" role="alert"><p className="msg">{c.msg}</p><button className="btn" onClick={() => setRetry((n) => n + 1)}>Retry</button></div>;
  const d = c.data;
  return (
    <div className="pane-body" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: "var(--text-xl)" }} className="mono">{d.case_id}</h2>
        <span className="num" style={{ color: "var(--color-text-muted)" }}>District {d.district} · window {d.window[0].slice(11, 16)}–{d.window[1]?.slice(11, 16) ?? "not recorded"} on {d.window[0].slice(0, 10)}</span>
        <span className="tag">{d.data_label}</span>
      </div>
      <dl className="facts">
        {d.facts.map((f) => (
          <div key={f.field} style={{ display: "contents" }}>
            <dt>{f.label}</dt>
            <dd>{f.value === null ? <span className="missing">Not recorded</span> : (
              <span className="cite" tabIndex={0}>{pretty(f.value)}
                <span className="tip" role="tooltip">Source: {d.case_id} · {f.field}{f.source.spans.length ? ` · narrative characters ${f.source.spans.map(([a, b]) => `${a}–${b}`).join(", ")}` : ""} · extracted by {d.extracted_by}</span>
              </span>)}
            </dd>
          </div>
        ))}
      </dl>
      <details>
        <summary>Narrative (cited passages highlighted)</summary>
        <p className="narrative">{marked}</p>
      </details>
    </div>
  );
}

function markSpans(d: CaseDetail): React.ReactNode[] {
  const spans = d.facts.flatMap((f) => f.source.spans).filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0]);
  const out: React.ReactNode[] = []; let pos = 0;
  spans.forEach(([a, b], i) => {
    if (a < pos) return;
    out.push(d.narrative.slice(pos, a));
    out.push(<mark key={i} className="span">{d.narrative.slice(a, b)}</mark>);
    pos = b;
  });
  out.push(d.narrative.slice(pos));
  return out;
}

function LinksView({ g, view, selectedCase, selectedPair, onCase, onPair, onRetry }: {
  g: Load<Graph>; view: View; selectedCase?: string; selectedPair?: string;
  onCase: (id: string) => void; onPair: (p: string, c: string) => void; onRetry: () => void;
}) {
  if (g.state === "loading") return <div className="state" aria-busy="true"><div className="skeleton tall" style={{ width: "60%" }} /><p>Loading links…</p></div>;
  if (g.state === "error") return <div className="state error" role="alert"><p className="msg">{g.msg}</p><button className="btn" onClick={onRetry}>Retry</button></div>;
  if (!g.data.edges.length) return <div className="state"><p>No links at this threshold yet. Lower “Show links from” or advance a day.</p></div>;
  if (view === "map") return <MapView graph={g.data} selectedCase={selectedCase} onCase={onCase} onPair={onPair} />;
  if (view === "table") return <EdgeTable g={g.data} selectedPair={selectedPair} onPair={onPair} />;
  return <WebGraph graph={g.data} selectedCase={selectedCase} selectedPair={selectedPair} onCase={onCase} onPair={onPair} />;
}

function EdgeTable({ g, selectedPair, onPair }: { g: Graph; selectedPair?: string; onPair: (p: string, c: string) => void }) {
  const rows = [...g.edges].sort((a, b) => b.prob - a.prob);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "auto" }}>
      <table className="data">
        <caption className="sr-only">Links between visible cases</caption>
        <thead><tr><th>Cases</th><th>Band</th><th className="num">p</th><th className="num">km</th><th className="num">Days</th><th className="num">Method overlap</th><th>Status</th></tr></thead>
        <tbody>{rows.map((e) => (
          <tr key={e.id} data-status={e.status} aria-selected={e.id === selectedPair}>
            <td><button className="btn quiet mono" onClick={() => onPair(e.id, e.source)}>{e.source} ↔ {e.target}</button></td>
            <td>{e.band}</td><td className="num">{e.prob.toFixed(2)}</td><td className="num">{e.distance_km.toFixed(1)}</td>
            <td className="num">{e.days_apart.toFixed(0)}</td><td className="num">{e.method_overlap.toFixed(2)}</td>
            <td>{{ suggested: "Suggested", accept: "Accepted", reject: "Rejected", defer: "Deferred" }[e.status]}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}
