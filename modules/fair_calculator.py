"""FAIR (Factor Analysis of Information Risk) Monte Carlo engine.

Implements the FAIR ontology:
    Vulnerability = max(0, TC - CS)      (clipped probability the threat succeeds)
    LEF  = TEF * Vulnerability           (loss events / year)
    LM   = PLM + SLM                     (loss magnitude per event, $)
    Risk = LEF * LM                      (annualized loss exposure, $)

All inputs are min / most-likely / max triples sampled from a PERT distribution.
"""
from dataclasses import dataclass, field

import numpy as np

import config

RISK_TIERS = [
    ("Low", 0, 10_000),
    ("Moderate", 10_000, 100_000),
    ("High", 100_000, 1_000_000),
    ("Critical", 1_000_000, float("inf")),
]

TIER_COLORS = {
    "Low": "#2ecc71",
    "Moderate": "#f1c40f",
    "High": "#e67e22",
    "Critical": "#e74c3c",
}


def pert_sample(low, mode, high, samples=10000, gamma=4, rng=None):
    """Sample from a PERT (modified beta) distribution."""
    if not (low <= mode <= high):
        raise ValueError(f"PERT requires low <= mode <= high, got {low}, {mode}, {high}")
    rng = rng or np.random.default_rng()
    if high == low:  # degenerate: all mass at one point
        return np.full(samples, float(low))
    alpha = 1 + gamma * (mode - low) / (high - low)
    beta = 1 + gamma * (high - mode) / (high - low)
    return low + (high - low) * rng.beta(alpha, beta, samples)


def classify_risk_tier(ale: float) -> str:
    """Classify an annualized loss exposure (P50) into a risk tier."""
    for tier, lo, hi in RISK_TIERS:
        if lo <= ale < hi:
            return tier
    return "Critical"


@dataclass
class FairInputs:
    tef_min: float = 0.1
    tef_ml: float = 0.5
    tef_max: float = 2.0
    tc_min: float = 0.3
    tc_ml: float = 0.6
    tc_max: float = 0.85
    cs_min: float = 0.4
    cs_ml: float = 0.65
    cs_max: float = 0.9
    plm_min: float = 10_000.0
    plm_ml: float = 75_000.0
    plm_max: float = 500_000.0
    slm_min: float = 5_000.0
    slm_ml: float = 25_000.0
    slm_max: float = 150_000.0

    def validate(self):
        for prefix in ("tef", "tc", "cs", "plm", "slm"):
            lo = getattr(self, f"{prefix}_min")
            ml = getattr(self, f"{prefix}_ml")
            hi = getattr(self, f"{prefix}_max")
            if not (lo <= ml <= hi):
                raise ValueError(f"{prefix.upper()}: require min <= most-likely <= max ({lo}, {ml}, {hi})")
        for prefix in ("tc", "cs"):
            if getattr(self, f"{prefix}_min") < 0 or getattr(self, f"{prefix}_max") > 1:
                raise ValueError(f"{prefix.upper()} must be within [0, 1]")
        if self.tef_min < 0:
            raise ValueError("TEF must be >= 0")


@dataclass
class FairResults:
    ale_samples: np.ndarray
    lef_samples: np.ndarray
    lm_samples: np.ndarray
    vuln_samples: np.ndarray
    percentiles: dict = field(default_factory=dict)
    risk_tier: str = ""

    @property
    def p10(self):
        return self.percentiles["p10"]

    @property
    def p50(self):
        return self.percentiles["p50"]

    @property
    def p90(self):
        return self.percentiles["p90"]


def run_simulation(inputs: FairInputs, iterations: int | None = None, seed: int | None = None) -> FairResults:
    """Run the FAIR Monte Carlo simulation."""
    inputs.validate()
    n = iterations or config.DEFAULT_MONTE_CARLO_ITERATIONS
    rng = np.random.default_rng(seed)

    tef = pert_sample(inputs.tef_min, inputs.tef_ml, inputs.tef_max, n, rng=rng)
    tc = pert_sample(inputs.tc_min, inputs.tc_ml, inputs.tc_max, n, rng=rng)
    cs = pert_sample(inputs.cs_min, inputs.cs_ml, inputs.cs_max, n, rng=rng)
    plm = pert_sample(inputs.plm_min, inputs.plm_ml, inputs.plm_max, n, rng=rng)
    slm = pert_sample(inputs.slm_min, inputs.slm_ml, inputs.slm_max, n, rng=rng)

    vuln = np.maximum(0.0, tc - cs)
    lef = tef * vuln
    lm = plm + slm
    ale = lef * lm

    percentiles = {
        "p10": float(np.percentile(ale, 10)),
        "p50": float(np.percentile(ale, 50)),
        "p90": float(np.percentile(ale, 90)),
        "mean": float(np.mean(ale)),
        "max": float(np.max(ale)),
    }

    return FairResults(
        ale_samples=ale,
        lef_samples=lef,
        lm_samples=lm,
        vuln_samples=vuln,
        percentiles=percentiles,
        risk_tier=classify_risk_tier(percentiles["p50"]),
    )
