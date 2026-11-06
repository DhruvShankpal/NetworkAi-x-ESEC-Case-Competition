"""Series = connected components over accepted links plus undecided links above threshold.
Rejected links never form edges (they stay visible in the UI as why-not history)."""
from __future__ import annotations

from typing import Iterable, Mapping

import networkx as nx


def build_series(pairs: Iterable[Mapping], threshold: float, min_size: int = 2) -> list[set[str]]:
    """pairs: dicts with case_a, case_b, prob, decision in {'accept','reject','defer',None}."""
    g = nx.Graph()
    for p in pairs:
        decision = p.get("decision")
        if decision == "reject":
            continue
        if decision == "accept" or p["prob"] >= threshold:
            g.add_edge(p["case_a"], p["case_b"])
    comps = [set(c) for c in nx.connected_components(g) if len(c) >= min_size]
    return sorted(comps, key=lambda c: (-len(c), min(c)))


def grow_series(seeds: list[set[str]], pairs: Iterable[Mapping], tau: float, rounds: int = 2) -> list[set[str]]:
    """Case-to-series evidence. A case joins a seed group when its COMBINED evidence against the
    group's members reaches tau: 1 - prod(1 - p_i) over its links to members ("noisy-OR").
    One weak link is not enough; several weak links to the same group can be. Rejected links
    never count. Each case joins at most one group (the one with the strongest evidence)."""
    groups = [set(s) for s in seeds]
    nbrs: dict[str, list[tuple[str, float]]] = {}
    for p in pairs:
        if p.get("decision") == "reject":
            continue
        nbrs.setdefault(p["case_a"], []).append((p["case_b"], p["prob"]))
        nbrs.setdefault(p["case_b"], []).append((p["case_a"], p["prob"]))
    for _ in range(rounds):
        owner = {c: k for k, g in enumerate(groups) for c in g}
        best: dict[str, tuple[float, int]] = {}
        for k, g in enumerate(groups):
            miss: dict[str, float] = {}
            for m in g:
                for c, pr in nbrs.get(m, ()):
                    if c not in owner:
                        miss[c] = miss.get(c, 1.0) * (1.0 - pr)
            for c, mp in miss.items():
                ev = 1.0 - mp
                if ev >= tau and ev > best.get(c, (0.0, -1))[0]:
                    best[c] = (ev, k)
        if not best:
            break
        for c, (_, k) in best.items():
            groups[k].add(c)
    return sorted(groups, key=lambda c: (-len(c), min(c)))
