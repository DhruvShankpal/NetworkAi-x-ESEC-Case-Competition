"""Glue: blocking -> features -> labels/scores. Used by training, eval and the API."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .blocking import BlockingConfig, candidate_pairs
from .features import pair_features
from .linkage import LinkageModel


def labelled_pairs(incidents: Sequence[Mapping[str, Any]], key: Mapping[str, Mapping[str, Any]],
                   cfg: BlockingConfig = BlockingConfig()):
    """Returns (pairs, raws, y). Linked = same offender (decoys are never linked)."""
    pairs, raws, y = [], [], []
    for i, j, block in candidate_pairs(incidents, cfg):
        a, b = incidents[i], incidents[j]
        pairs.append((a["case_id"], b["case_id"], block))
        raws.append(pair_features(a, b))
        y.append(int(key[a["case_id"]]["offender_id"] == key[b["case_id"]]["offender_id"]))
    return pairs, raws, y


def true_pair_count(key: Mapping[str, Mapping[str, Any]]) -> int:
    from collections import Counter
    sizes = Counter(v["offender_id"] for v in key.values())
    return sum(n * (n - 1) // 2 for n in sizes.values())


def score_pairs(model: LinkageModel, incidents: Sequence[Mapping[str, Any]],
                cfg: BlockingConfig = BlockingConfig(), replay_date=None) -> list[dict[str, Any]]:
    out = []
    for i, j, block in candidate_pairs(incidents, cfg, replay_date):
        a, b = incidents[i], incidents[j]
        raw = pair_features(a, b)
        prob, contrib = model.score(raw)
        out.append({"case_a": a["case_id"], "case_b": b["case_id"], "block": block,
                    **raw, "prob": prob, "contributions": contrib, "model_version": model.version})
    return out
