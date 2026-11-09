import math

from app.api.router import _finite_json


def test_non_finite_exported_metrics_are_null():
    source = {"valid": 0.95, "missing": float("nan"), "nested": [float("inf")]}
    result = _finite_json(source)
    assert result == {"valid": 0.95, "missing": None, "nested": [None]}
