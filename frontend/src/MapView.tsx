import { MapboxOverlay } from "@deck.gl/mapbox";
import { ArcLayer, ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { Graph, GraphEdge, GraphNode } from "./api";

// Same selection state as the web. No basemap tiles: the demo runs offline and never shows addresses.
const tok = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgb = (hex: string, a = 255): [number, number, number, number] => {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), a];
};

type Props = { graph: Graph; selectedCase?: string; onCase: (id: string) => void; onPair: (pairId: string, caseId: string) => void };

export function MapView({ graph, selectedCase, onCase, onPair }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const m = new maplibregl.Map({
      container: host.current, attributionControl: false,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": tok("--color-bg") } }] },
      center: [-122.33, 47.6], zoom: 10.3,
    });
    const o = new MapboxOverlay({ interleaved: false, layers: [] });
    m.addControl(o);
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m; overlay.current = o;
    return () => { m.remove(); map.current = null; overlay.current = null; };
  }, []);

  useEffect(() => {
    const o = overlay.current;
    if (!o) return;
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const accent = rgb(tok("--color-accent")), edge = rgb(tok("--color-edge"));
    const color = (e: GraphEdge) => (e.status === "accept" ? accent : e.status === "reject" ? rgb(tok("--color-edge"), 40) : [...edge.slice(0, 3), 190] as [number, number, number, number]);
    const hood = new Set<string>();
    if (selectedCase) { hood.add(selectedCase); graph.edges.forEach((e) => { if (e.source === selectedCase) hood.add(e.target); if (e.target === selectedCase) hood.add(e.source); }); }
    o.setProps({
      layers: [
        new ArcLayer<GraphEdge>({
          id: "links", data: graph.edges, pickable: true, greatCircle: false,
          getSourcePosition: (e) => [byId.get(e.source)!.lon, byId.get(e.source)!.lat],
          getTargetPosition: (e) => [byId.get(e.target)!.lon, byId.get(e.target)!.lat],
          getSourceColor: (e) => (selectedCase && !hood.has(e.source) ? [...color(e).slice(0, 3), 60] as [number, number, number, number] : color(e)),
          getTargetColor: (e) => (selectedCase && !hood.has(e.target) ? [...color(e).slice(0, 3), 60] as [number, number, number, number] : color(e)),
          getWidth: (e) => 1 + e.prob * 4, onClick: ({ object }) => object && onPair(object.id, object.source),
          updateTriggers: { getSourceColor: selectedCase, getTargetColor: selectedCase },
        }),
        new ScatterplotLayer<GraphNode>({
          id: "cases", data: graph.nodes, pickable: true, radiusUnits: "pixels",
          getPosition: (n) => [n.lon, n.lat], getRadius: (n) => (n.id === selectedCase ? 8 : 5),
          getFillColor: (n) => rgb(tok(n.id === selectedCase ? "--color-accent" : "--color-node-res"), selectedCase && !hood.has(n.id) ? 100 : 230),
          getLineColor: rgb(tok("--color-bg")), stroked: true, lineWidthMinPixels: 1,
          onClick: ({ object }) => object && onCase(object.id),
          updateTriggers: { getRadius: selectedCase, getFillColor: selectedCase },
        }),
      ],
    });
    if (graph.nodes.length && map.current) {
      const lons = graph.nodes.map((n) => n.lon), lats = graph.nodes.map((n) => n.lat);
      map.current.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 60, maxZoom: 13, duration: 0 });
    }
  }, [graph, selectedCase, onCase, onPair]);

  return (
    <>
      <div className="graph" aria-label="Map of linked cases. The Table view lists the same links." role="img">
        {/* maplibre's stylesheet makes its container position:relative, so it gets its own sized element */}
        <div ref={host} style={{ width: "100%", height: "100%" }} />
      </div>
      <div className="map-note">Locations shifted and generalized. No basemap in this offline demo.</div>
    </>
  );
}
