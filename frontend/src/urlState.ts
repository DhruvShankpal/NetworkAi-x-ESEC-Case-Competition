import { useCallback, useEffect, useState } from "react";

// All view state lives in the URL so a session can be reloaded and reviewed.
export type View = "web" | "map" | "table";
export type Tab = "series" | "sleeper" | "full";
export type UrlState = {
  s: string; analyst: string; day?: string; case?: string; pair?: string;
  tab: Tab; view: View; min: number; rej: boolean;
};

function read(): UrlState {
  const p = new URLSearchParams(window.location.search);
  const num = Number(p.get("min"));
  return {
    s: p.get("s") || "S-01",
    analyst: p.get("analyst") || "anon-2",
    day: p.get("day") || undefined,
    case: p.get("case") || undefined,
    pair: p.get("pair") || undefined,
    tab: (["series", "sleeper", "full"].includes(p.get("tab") || "") ? p.get("tab") : "series") as Tab,
    view: (["web", "map", "table"].includes(p.get("view") || "") ? p.get("view") : "web") as View,
    min: Number.isFinite(num) && num > 0 ? Math.min(Math.max(num, 0.05), 0.95) : 0.3,
    rej: p.get("rej") !== "0",
  };
}

export function useUrlState(): [UrlState, (patch: Partial<UrlState>) => void] {
  const [st, setSt] = useState<UrlState>(read);
  useEffect(() => {
    const on = () => setSt(read());
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const update = useCallback((patch: Partial<UrlState>) => {
    setSt((prev) => {
      const next = { ...prev, ...patch };
      const p = new URLSearchParams();
      p.set("s", next.s); p.set("analyst", next.analyst);
      if (next.day) p.set("day", next.day);
      if (next.case) p.set("case", next.case);
      if (next.pair) p.set("pair", next.pair);
      p.set("tab", next.tab); p.set("view", next.view);
      p.set("min", String(next.min)); p.set("rej", next.rej ? "1" : "0");
      window.history.replaceState(null, "", `?${p.toString()}`);
      return next;
    });
  }, []);
  return [st, update];
}
