"""SLO math: percentile vectors, window summaries, hypothesis grading."""

from __future__ import annotations

import time

from faultline.models import SloSpec
from faultline.telemetry.probe import ProbeSample
from faultline.telemetry.slo import evaluate_slo, percentile, summarize


def _sample(ok: bool = True, latency: float | None = 10.0) -> ProbeSample:
    return ProbeSample(0, "http://x/health", ok, 200 if ok else 0, latency, time.time())


class TestPercentile:
    def test_empty_returns_none(self):
        assert percentile([], 50) is None

    def test_single_value(self):
        assert percentile([42.0], 99) == 42.0

    def test_known_vectors(self):
        values = [float(i) for i in range(1, 11)]  # 1..10
        assert abs(percentile(values, 50) - 5.5) < 1e-9
        assert abs(percentile(values, 95) - 9.55) < 1e-9
        assert abs(percentile(values, 99) - 9.91) < 1e-9

    def test_extremes(self):
        values = [3.0, 1.0, 2.0]
        assert percentile(values, 0) == 1.0
        assert percentile(values, 100) == 3.0


class TestSummarize:
    def test_mixed_samples(self):
        samples = [_sample(True, 10.0), _sample(True, 20.0), _sample(False)]
        m = summarize(samples)
        assert m["samples"] == 3
        assert m["ok"] == 2
        assert m["failed"] == 1
        assert m["error_rate"] == round(1 / 3, 4)
        assert m["p50_ms"] == 15.0

    def test_no_samples(self):
        m = summarize([])
        assert m["samples"] == 0
        assert m["error_rate"] is None
        assert m["p95_ms"] is None

    def test_all_failed_has_no_latency(self):
        m = summarize([_sample(False), _sample(False)])
        assert m["ok"] == 0
        assert m["p95_ms"] is None
        assert m["error_rate"] == 1.0


class TestEvaluateSlo:
    def test_pass_when_within_limits(self):
        slo = SloSpec(name="fast", window="baseline", p95_latency_ms=100, error_rate_max=0.5)
        samples = [_sample(True, 10.0), _sample(True, 20.0), _sample(False)]
        result = evaluate_slo(slo, samples)
        assert result.passed is True
        assert len(result.checks) == 2

    def test_fail_when_p95_exceeded(self):
        slo = SloSpec(name="fast", window="baseline", p95_latency_ms=15)
        samples = [_sample(True, 10.0), _sample(True, 40.0)]
        result = evaluate_slo(slo, samples)
        assert result.passed is False
        assert result.checks[0]["passed"] is False

    def test_no_data_fails_p95_check(self):
        slo = SloSpec(name="fast", window="fault", p95_latency_ms=100)
        result = evaluate_slo(slo, [_sample(False), _sample(False)])
        assert result.passed is False

    def test_zero_samples_fails_error_rate_check(self):
        slo = SloSpec(name="up", window="recovery", error_rate_max=0.0)
        result = evaluate_slo(slo, [])
        assert result.passed is False

    def test_evidence_carries_metrics(self):
        slo = SloSpec(name="fast", window="baseline", p95_latency_ms=100)
        samples = [_sample(True, 10.0), _sample(True, 20.0)]
        result = evaluate_slo(slo, samples)
        assert result.evidence["p95_ms"] is not None
        assert result.to_dict()["window"] == "baseline"
