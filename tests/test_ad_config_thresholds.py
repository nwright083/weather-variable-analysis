"""
test_ad_config_thresholds.py — the per-model threshold binding is a money-safety
guardrail: switching the forecast model must switch to that model's *correct* alert
threshold automatically, so ads never fire at the wrong rate.

Authoritative thresholds live in model_metrics.json (tracked in git):
  exact_pittsburgh     -> thr_opt_daily = 0.3681   (daily city-wide; DEFAULT)
  pittsburgh_proximity -> thr_opt       = 0.2038   (per-tract)

Run:  python -m pytest tests/test_ad_config_thresholds.py -q
"""

import os
import sys
import json

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import ad_config


def _model_metrics():
    with open(os.path.join(REPO_ROOT, "model_metrics.json")) as f:
        return json.load(f)["models"]


class TestModelRegistry:
    def test_default_model_is_exact_pittsburgh(self):
        assert ad_config.MODEL_MODE == "exact_pittsburgh"

    def test_registry_has_both_models(self):
        assert set(ad_config.MODEL_REGISTRY) == {"exact_pittsburgh", "pittsburgh_proximity"}

    def test_exact_pittsburgh_threshold_is_0_3681(self):
        assert ad_config.resolve_threshold("exact_pittsburgh") == 0.3681

    def test_proximity_threshold_is_0_2038(self):
        assert ad_config.resolve_threshold("pittsburgh_proximity") == 0.2038

    def test_default_model_resolves_without_argument(self):
        # No model given -> uses ad_config.MODEL_MODE (exact_pittsburgh -> 0.3681)
        assert ad_config.resolve_threshold() == 0.3681

    def test_explicit_override_wins(self):
        assert ad_config.resolve_threshold("exact_pittsburgh", override=0.5) == 0.5

    def test_unknown_model_raises(self):
        with pytest.raises((KeyError, ValueError)):
            ad_config.resolve_threshold("not_a_real_model")


class TestThresholdsMatchAuthoritativeSource:
    """Drift guard: registry values must equal model_metrics.json, using each
    model's model-specific metric key (exact -> thr_opt_daily, proximity -> thr_opt)."""

    def test_registry_matches_model_metrics(self):
        metrics = _model_metrics()
        for model, entry in ad_config.MODEL_REGISTRY.items():
            metric_key = entry["metric_key"]
            expected = metrics[model][metric_key]
            assert entry["threshold"] == expected, (
                f"{model}: registry threshold {entry['threshold']} != "
                f"model_metrics {metric_key}={expected}"
            )
