import cytoscape from "cytoscape";
import type { Core, ElementDefinition, NodeSingular, Stylesheet } from "cytoscape";
import fcose from "cytoscape-fcose";
import { useEffect, useRef, useState } from "react";
import type { Graph, GraphEdge } from "./api";

cytoscape.use(fcose);

const tok = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const RAMP = ["--color-ramp-1", "--color-ramp-2", "--color-ramp-3", "--color-ramp-4"];

type Props = { graph: Graph; selectedCase?: string; selectedPair?: string;
  onCase: (id: string) => void; onPair: (pairId: string, caseId: string) => void };

export function WebGraph({ graph, selectedCase, selectedPair, onCase, onPair }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [hover, setHover] = useState<{ e: GraphEdge; x: number; y: number } | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const c = cytoscape({
      container: host.current, minZoom: 0.2, maxZoom: 3, wheelSensitivity: 0.25,
      style: [
        { selector: "node", style: {
          "background-color": "data(fill)", "border-width": 1, "border-color": tok("--color-border"),
          width: 18, height: 18, label: "", color: tok("--color-text"), "font-family": tok("--font-mono"),
          "font-size": 10, "text-valign": "bottom", "text-margin-y": 4 } },
        { selector: "node[tt = 'commercial']", style: { shape: "round-rectangle" } },
        { selector: "node[?isNew]", style: { "border-width": 2, "border-color": tok("--color-text-muted") } },
        { selector: "node:parent", style: {
          "background-color": tok("--color-surface"), "background-opacity": 0.6, "border-color": tok("--color-border"),
          "border-width": 1, shape: "round-rectangle", label: "data(label)", "font-family": tok("--font-sans"),
          "font-size": 11, color: tok("--color-text-muted"), "text-valign": "top", "text-halign": "center",
          "text-margin-y": -4, padding: "14px" } as never },
        { selector: "node:parent[status = 'active']", style: { "border-color": tok("--color-accent") } },
        { selector: "edge", style: {
          width: "mapData(prob, 0.05, 1, 1, 6)", "line-color": tok("--color-edge"), "line-style": "dashed",
          "curve-style": "bezier", opacity: 0.85 } },
        { selector: "edge[status = 'accept']", style: { "line-style": "solid", "line-color": tok("--color-accent"), opacity: 1 } },
        { selector: "edge[status = 'reject']", style: { opacity: 0.15, "line-style": "solid" } },
        { selector: "edge[status = 'defer']", style: { "line-style": "dotted" } },
        { selector: ".dim", style: { opacity: 0.4 } },
        { selector: "edge.dim[status = 'reject']", style: { opacity: 0.08 } },
        { selector: ".hl", style: { opacity: 1 } },
        { selector: "node.sel", style: { "border-width": 3, "border-color": tok("--color-accent"), label: "data(id)" } },
        { selector: "edge.sel", style: { width: 6, opacity: 1 } },
        { selector: "node.lbl", style: { label: "data(id)" } },
      ] as Stylesheet[],
    });
    c.on("tap", "node", (e) => { if (!e.target.isParent()) onCase(e.target.id()); });
    c.on("tap", "edge", (e) => onPair(e.target.id(), e.target.data("source")));
    c.on("mouseover", "edge", (e) => {
      const p = e.renderedPosition || e.target.renderedMidpoint();
      setHover({ e: e.target.data("raw") as GraphEdge, x: p.x, y: p.y });
    });
    c.on("mouseout", "edge", () => setHover(null));
    c.on("zoom", () => c.nodes().not(":parent").toggleClass("lbl", c.zoom() >= 1.2));
    cy.current = c;
    return () => { c.destroy(); cy.current = null; };
  }, [onCase, onPair]);

  // Sync elements incrementally so the web grows in place when a day advances.
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const districts = [...new Set(graph.nodes.map((n) => n.district))].sort();
    const els: ElementDefinition[] = [
      ...graph.series.map((s) => ({ group: "nodes" as const, data: {
        id: s.series_id, status: s.status,
        label: `${s.series_id} · ${s.size} cases · first seen day ${s.first_seen_day}` } })),
      ...graph.nodes.map((n) => ({ group: "nodes" as const, data: {
        id: n.id, tt: n.target_type, isNew: n.new_today, parent: n.series_id || undefined,
        fill: tok(RAMP[districts.indexOf(n.district) % RAMP.length]) } })),
      ...graph.edges.map((e) => ({ group: "edges" as const, data: {
        id: e.id, source: e.source, target: e.target, prob: e.prob, status: e.status, raw: e } })),
    ];
    const want = new Set(els.map((e) => e.data.id as string));
    c.batch(() => {
      c.elements().filter((el) => !want.has(el.id())).remove();
      for (const el of els) {
        const ex = c.getElementById(el.data.id as string);
        if (ex.nonempty()) {
          if (ex.isNode() && (ex.data("parent") || null) !== (el.data.parent || null)) {
            ex.move({ parent: (el.data.parent as string) || null });
          }
          ex.data(el.data);
        } else {
          c.add(el);
        }
      }
    });
    c.one("layoutstop", () => c.fit(undefined, 48));
    c.layout({ name: "fcose", randomize: c.nodes().toArray().every((n) => !n.scratch("placed")), animate: !reduced(),
      animationDuration: 250, fit: false,
      nodeRepulsion: 6000, idealEdgeLength: 70, packComponents: true } as cytoscape.LayoutOptions).run();
    c.nodes().forEach((n) => { n.scratch("placed", true); });
  }, [graph]);

  // Selection: accent ring, its edges brighten, everything else drops to 40%.
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.elements().removeClass("sel dim hl");
    const node = selectedCase ? c.getElementById(selectedCase) : null;
    if (node && node.nonempty()) {
      const hood = node.closedNeighborhood();
      c.elements().not(hood).not(":parent").addClass("dim");
      hood.addClass("hl");
      node.addClass("sel");
    }
    if (selectedPair) c.getElementById(selectedPair).addClass("sel");
  }, [selectedCase, selectedPair, graph]);

  // Keyboard: arrows move to the nearest neighbour in that direction; Enter selects.
  const onKey = (ev: React.KeyboardEvent) => {
    const c = cy.current;
    if (!c) return;
    const cur = (selectedCase && c.getElementById(selectedCase).nonempty())
      ? c.getElementById(selectedCase) as NodeSingular : null;
    if (!cur) {
      if (ev.key.startsWith("Arrow") || ev.key === "Enter") {
        const first = c.nodes().not(":parent").first();
        if (first.nonempty()) { ev.preventDefault(); onCase(first.id()); }
      }
      return;
    }
    const dir: Record<string, [number, number]> = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (dir[ev.key]) {
      ev.preventDefault();
      const [dx, dy] = dir[ev.key];
      const p = cur.position();
      let best: NodeSingular | null = null, bestScore = Infinity;
      cur.neighborhood("node").forEach((n) => {
        const q = n.position(); const vx = q.x - p.x, vy = q.y - p.y;
        const along = vx * dx + vy * dy; if (along <= 0) return;
        const score = Math.hypot(vx, vy) / (along / Math.hypot(vx, vy));
        if (score < bestScore) { bestScore = score; best = n; }
      });
      if (best) onCase((best as NodeSingular).id());
    }
    if (ev.key === "Escape") c.fit(undefined, 40);
  };

  return (
    <>
      <div ref={host} className="graph" tabIndex={0} role="application" onKeyDown={onKey}
        aria-label={`Web of cases: ${graph.nodes.length} cases and ${graph.edges.length} links. Arrow keys move between linked cases. The Table view lists the same links.`} />
      {hover && (
        <div className="hover-card num" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <div className="mono">{hover.e.source} ↔ {hover.e.target}</div>
          <div><strong>{hover.e.band}</strong> (p = {hover.e.prob.toFixed(2)})</div>
          <div>{hover.e.distance_km.toFixed(1)} km · {hover.e.days_apart.toFixed(0)} days · method overlap {hover.e.method_overlap.toFixed(2)}</div>
          <div style={{ color: "var(--color-text-muted)" }}>Status: {{ suggested: "suggested", accept: "accepted", reject: "rejected", defer: "deferred" }[hover.e.status]}</div>
        </div>
      )}
      <div className="legend" aria-hidden="true">
        <span><i />Suggested</span><span><i className="acc" />Accepted</span><span><i className="rej" />Rejected</span>
        <span>● residential · ▢ commercial</span>
      </div>
    </>
  );
}
