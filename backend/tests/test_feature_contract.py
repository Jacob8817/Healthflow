import json
from pathlib import Path

import pandas as pd
import numpy as np

from app.ai.forecasting.feature_builder import ForecastFeatureBuilder, HospitalHistoryFeatureBuilder


ROOT = Path(__file__).resolve().parents[1]


def test_latest_feature_row_matches_exported_schema():
    schema = json.loads((ROOT / "model_artifacts/emergency_admissions_forecast/feature_schema.json").read_text())
    builder = ForecastFeatureBuilder(ROOT / "dataset/processed/nhs_england_ae", schema)
    provider = builder.list_providers()[0]
    frame, context = builder.build(provider["code"], provider["latest_month"])
    assert list(frame.columns) == schema["features"]
    assert frame.shape == (1, len(schema["features"]))
    assert context["target_month"] == str(pd.Period(context["feature_month"], "M") + 1)


def test_hospital_history_builder_reproduces_exported_engineering():
    schema = json.loads((ROOT / "model_artifacts/emergency_admissions_forecast/feature_schema.json").read_text())
    data = pd.read_parquet(ROOT / "dataset/processed/nhs_england_ae/forecasting_features.parquet")
    rows = data[data.provider_code.eq("RTE")].sort_values("feature_month")
    history = rows[[
        "feature_month", "emergency_admissions", "total_ae_attendances",
        "attendances_under_4_hours", "decision_to_admit_waits_over_4_hours",
    ]].rename(columns={"feature_month": "month"}).to_dict("records")
    actual, context = HospitalHistoryFeatureBuilder(schema).build("RTE", "Parity hospital", history)
    expected = rows.iloc[-1]
    numeric = schema["numerical"]
    np.testing.assert_allclose(
        actual.loc[0, numeric].astype(float), expected[numeric].astype(float),
        rtol=1e-10, atol=1e-10, equal_nan=True,
    )
    assert context["target_month"] == str(pd.Period(rows.feature_month.iloc[-1], "M") + 1)
