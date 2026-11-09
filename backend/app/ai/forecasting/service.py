from __future__ import annotations
import time
import uuid
import numpy as np
from app.ai.forecasting.feature_builder import HospitalHistoryFeatureBuilder
from app.ai.forecasting.model_loader import ForecastModelLoader
from app.core.metrics import FORECAST_DURATION, FORECAST_FAILURES, FORECAST_REQUESTS

DISCLAIMER = "Aggregate operational forecasting only; not for patient-level or clinical decisions."


class ForecastService:
    def __init__(self, loader: ForecastModelLoader):
        self.loader = loader

    def forecast_hospital(self, hospital_identifier: str, hospital_name: str, history: list[dict]) -> dict:
        FORECAST_REQUESTS.inc()
        started = time.perf_counter()
        try:
            bundle = self.loader.load()
            builder = HospitalHistoryFeatureBuilder(bundle.feature_schema)
            frame, context = builder.build(hospital_identifier, hospital_name, history)
            raw = float(bundle.pipeline.predict(frame)[0])
            clipped = raw < 0
            displayed = max(0, int(round(raw)))
            importance = []
            # Exported importance is preferred and is not interpreted causally.
            importance_path = self.loader.model_dir / "feature_importance.csv"
            if importance_path.exists():
                import pandas as pd
                importance = pd.read_csv(importance_path).head(5)[
                    ["feature", "importance_mean"]
                ].to_dict("records")
            return {
                "forecast_run_id": str(uuid.uuid4()),
                "hospital": {"identifier": context["code"], "name": context["name"]},
                "feature_month": context["feature_month"],
                "target_month": context["target_month"],
                "raw_prediction": raw,
                "predicted_emergency_admissions": displayed,
                "forecast_interval": {
                    "lower_80": None, "upper_80": None, "lower_95": None,
                    "upper_95": None, "method": None,
                },
                "model": {
                    "name": "Random Forest Regressor",
                    "version": bundle.checksum[:12],
                    "primary_metric": "WAPE",
                    "validation_wape_percent": round(bundle.validation_metrics["wape"] * 100, 3),
                    "test_wape_percent": round(bundle.test_metrics["wape"] * 100, 3),
                },
                "data": {
                    "source": bundle.metadata["data_source"],
                    "history_start_month": context["history_start_month"],
                    "history_end_month": context["history_end_month"],
                },
                "important_factors": importance,
                "warnings": (["Negative raw prediction was clipped to zero."] if clipped else []) + [
                    "This hospital identifier was not part of the exported training categories. "
                    "Complete local shadow validation before operational use."
                ],
                "disclaimer": DISCLAIMER,
            }
        except Exception as exc:
            FORECAST_FAILURES.labels(reason=type(exc).__name__).inc()
            raise
        finally:
            FORECAST_DURATION.observe(time.perf_counter() - started)
