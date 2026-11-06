// Top three signed contributions to the log-odds, as a small diverging bar.
// Positive goes right, negative left. One neutral colour for both signs; labels in ink.
export function ContribBar({ items }: { items: [string, number][] }) {
  const max = Math.max(1, ...items.map(([, v]) => Math.abs(v)));
  const W = 300, mid = 150, rowH = 22, half = 120;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${items.length * rowH + 4}`} role="img"
      aria-label={`Score contributions: ${items.map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")}`}>
      <line x1={mid} x2={mid} y1={0} y2={items.length * rowH + 4} stroke="var(--color-border)" strokeWidth={1} />
      {items.map(([k, v], i) => {
        const w = (Math.abs(v) / max) * half;
        const y = i * rowH + 4;
        return (
          <g key={k}>
            <rect x={v >= 0 ? mid : mid - w} y={y} width={Math.max(w, 1)} height={12} rx={2} fill="var(--color-edge)" />
            <text x={v >= 0 ? mid - 6 : mid + 6} y={y + 10} textAnchor={v >= 0 ? "end" : "start"}
              fontSize={12} fill="var(--color-text)" style={{ fontVariantNumeric: "tabular-nums" }}>
              {v >= 0 ? `${k} +${v.toFixed(1)}` : `${k} ${v.toFixed(1)}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
