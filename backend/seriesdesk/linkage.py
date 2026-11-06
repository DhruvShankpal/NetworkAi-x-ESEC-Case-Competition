"""Deterministic pairwise linkage model (logistic regression).

Per-feature contributions to the log-odds are coef_j * x_j. Because the model is
additive in log-odds, these are exact (logit = intercept + sum(contributions)).
The model is persisted as JSON (no pickle) so it is diffable and hashable.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression

# `both_glass` was dropped: collinear with mo_jaccard, it took a negative coefficient on
# held-out synthetic data, i.e. "both glass broken" would be shown as evidence AGAINST a link.
DESIGN_FEATURES = ("log_distance_km", "log_days_apart", "mo_jaccard",
                   "same_target_type", "both_night")

PLAIN_LABELS = {
    "log_distance_km": "distance",
    "log_days_apart": "time gap",
    "mo_jaccard": "MO overlap",
    "same_target_type": "same target type",
    "both_night": "both at night",
}


def design_row(raw: Mapping[str, float]) -> list[float]:
    return [
        math.log1p(raw["distance_km"]),
        math.log1p(raw["days_apart"]),
        raw["mo_jaccard"],
        raw["same_target_type"],
        raw["both_night"],
    ]


def band(prob: float) -> str:
    """Plain-language uncertainty band shown before the number (spec §6.3)."""
    if prob >= 0.7:
        return "Strong"
    if prob >= 0.4:
        return "Possible"
    return "Weak"


@dataclass
class LinkageModel:
    version: str
    coef: list[float] = field(default_factory=list)
    intercept: float = 0.0
    features: tuple[str, ...] = DESIGN_FEATURES

    # ---- training -------------------------------------------------------
    @classmethod
    def fit(cls, raws: Sequence[Mapping[str, float]], y: Sequence[int], version: str,
            C: float = 1.0, class_weight: str | None = None) -> "LinkageModel":
        """Unweighted by default so `prob` stays calibrated to the candidate base rate.
        class_weight='balanced' (spec v1.0) inflated probabilities: at p>=0.7 connected
        components chained ~1,000 unrelated cases into series on held-out synthetic data."""
        X = np.array([design_row(r) for r in raws], dtype=float)
        y_arr = np.asarray(y, dtype=int)
        if len(set(y_arr.tolist())) < 2:
            raise ValueError("training data needs both linked and unlinked pairs")
        lr = LogisticRegression(l1_ratio=0, C=C,  # L2
                                class_weight=class_weight, max_iter=2000)
        lr.fit(X, y_arr)
        return cls(version=version, coef=lr.coef_[0].tolist(), intercept=float(lr.intercept_[0]))

    # ---- scoring --------------------------------------------------------
    def contributions(self, raw: Mapping[str, float]) -> dict[str, float]:
        x = design_row(raw)
        return {f: c * v for f, c, v in zip(self.features, self.coef, x)}

    def score(self, raw: Mapping[str, float]) -> tuple[float, dict[str, float]]:
        contrib = self.contributions(raw)
        logit = self.intercept + sum(contrib.values())
        prob = 1.0 / (1.0 + math.exp(-logit))
        return prob, contrib

    def score_many(self, raws: Iterable[Mapping[str, float]]) -> np.ndarray:
        X = np.array([design_row(r) for r in raws], dtype=float)
        if X.size == 0:
            return np.array([])
        logit = self.intercept + X @ np.asarray(self.coef)
        return 1.0 / (1.0 + np.exp(-logit))

    @staticmethod
    def top_reasons(contrib: Mapping[str, float], k: int = 3) -> list[tuple[str, float]]:
        ranked = sorted(contrib.items(), key=lambda kv: abs(kv[1]), reverse=True)[:k]
        return [(PLAIN_LABELS[f], round(v, 2)) for f, v in ranked]

    # ---- persistence ----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({"version": self.version, "features": list(self.features),
                           "coef": self.coef, "intercept": self.intercept},
                          sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "LinkageModel":
        d = json.loads(s)
        if tuple(d["features"]) != DESIGN_FEATURES:
            raise ValueError(f"feature mismatch: {d['features']}")
        return cls(version=d["version"], coef=d["coef"], intercept=d["intercept"])

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()
