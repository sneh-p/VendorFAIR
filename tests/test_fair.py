"""Unit tests for the FAIR Monte Carlo calculator."""
import time

import numpy as np
import pytest

from modules.fair_calculator import (
    FairInputs,
    classify_risk_tier,
    pert_sample,
    run_simulation,
)


class TestPertSample:
    def test_within_bounds(self):
        s = pert_sample(1.0, 5.0, 10.0, samples=5000)
        assert s.min() >= 1.0 and s.max() <= 10.0

    def test_mode_pull(self):
        s = pert_sample(0.0, 8.0, 10.0, samples=20000, rng=np.random.default_rng(42))
        assert 6.0 < np.median(s) < 9.0

    def test_degenerate_point(self):
        s = pert_sample(5.0, 5.0, 5.0, samples=100)
        assert np.all(s == 5.0)

    def test_invalid_order_raises(self):
        with pytest.raises(ValueError):
            pert_sample(10.0, 5.0, 1.0)


class TestRiskTier:
    @pytest.mark.parametrize(
        "ale,tier",
        [
            (0, "Low"),
            (9_999, "Low"),
            (10_000, "Moderate"),
            (99_999, "Moderate"),
            (100_000, "High"),
            (999_999, "High"),
            (1_000_000, "Critical"),
            (50_000_000, "Critical"),
        ],
    )
    def test_classification(self, ale, tier):
        assert classify_risk_tier(ale) == tier


class TestSimulation:
    def test_percentile_ordering(self):
        results = run_simulation(FairInputs(), iterations=10_000, seed=7)
        assert results.p10 <= results.p50 <= results.p90

    def test_ale_nonnegative(self):
        results = run_simulation(FairInputs(), iterations=10_000, seed=7)
        assert results.ale_samples.min() >= 0.0

    def test_iteration_count(self):
        results = run_simulation(FairInputs(), iterations=10_000)
        assert len(results.ale_samples) == 10_000

    def test_vulnerability_clipped(self):
        # CS always exceeds TC → vulnerability and ALE must be exactly zero
        inputs = FairInputs(tc_min=0.1, tc_ml=0.2, tc_max=0.3,
                            cs_min=0.7, cs_ml=0.8, cs_max=0.9)
        results = run_simulation(inputs, iterations=5_000, seed=1)
        assert results.vuln_samples.max() == 0.0
        assert results.ale_samples.max() == 0.0
        assert results.risk_tier == "Low"

    def test_runtime_under_3_seconds(self):
        start = time.perf_counter()
        run_simulation(FairInputs(), iterations=10_000)
        assert time.perf_counter() - start < 3.0

    def test_sensible_magnitude(self):
        # ALE can never exceed worst-case TEF * max(LM)
        inputs = FairInputs()
        results = run_simulation(inputs, iterations=10_000, seed=3)
        worst_case = inputs.tef_max * (inputs.plm_max + inputs.slm_max)
        assert results.ale_samples.max() <= worst_case

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError):
            run_simulation(FairInputs(tc_min=0.9, tc_ml=0.5, tc_max=0.2))
        with pytest.raises(ValueError):
            run_simulation(FairInputs(cs_max=1.5))

    def test_reproducible_with_seed(self):
        r1 = run_simulation(FairInputs(), iterations=1_000, seed=99)
        r2 = run_simulation(FairInputs(), iterations=1_000, seed=99)
        assert np.array_equal(r1.ale_samples, r2.ale_samples)
