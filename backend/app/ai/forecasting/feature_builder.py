from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from app.ai.forecasting.errors import FeatureValidationError, ProviderHistoryError


class ForecastFeatureBuilder:
    """Resolve a leakage-safe exported feature row for provider/month inference."""

    def __init__(self, data_dir: Path, feature_schema: dict) -> None:
        self.data_dir = data_dir.resolve()
        self.features = list(feature_schema["features"])
        self._table: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._table is None:
            path = self.data_dir / "forecasting_features.parquet"
            if not path.is_file():
                raise ProviderHistoryError(f"Processed feature table is missing: {path}")
            self._table = pd.read_parquet(path)
        return self._table

    def provider_summary(self, provider_code: str) -> dict:
        data = self._load()
        rows = data[data.provider_code.eq(provider_code)].sort_values("feature_month")
        if rows.empty:
            raise ProviderHistoryError(f"Unknown NHS provider code: {provider_code}")
        return {
            "code": provider_code,
            "name": str(rows.provider_name.iloc[-1]),
            "history_start_month": str(rows.feature_month.iloc[0]),
            "history_end_month": str(rows.feature_month.iloc[-1]),
            "months": int(len(rows)),
        }

    def build(self, provider_code: str, feature_month: str = "latest") -> tuple[pd.DataFrame, dict]:
        data = self._load()
        rows = data[data.provider_code.eq(provider_code)].sort_values("feature_month")
        if rows.empty:
            raise ProviderHistoryError(f"Unknown NHS provider code: {provider_code}")
        if feature_month == "latest":
            row = rows.iloc[-1]
        else:
            match = rows[rows.feature_month.eq(feature_month)]
            if match.empty:
                raise ProviderHistoryError(
                    f"Provider {provider_code} has no data for feature month {feature_month}."
                )
            row = match.iloc[-1]
        if len(rows[rows.feature_month.le(row.feature_month)]) < 12:
            raise ProviderHistoryError("At least 12 months of provider history are required.")
        missing = [name for name in self.features if name not in row.index]
        if missing:
            raise FeatureValidationError(f"Missing required exported features: {missing}")
        frame = pd.DataFrame([{name: row[name] for name in self.features}],
                             columns=self.features)
        frame = frame.replace({pd.NA: np.nan})
        unexpected = set(frame.columns) - set(self.features)
        if unexpected or list(frame.columns) != self.features:
            raise FeatureValidationError("Final feature order/schema mismatch.")
        context = self.provider_summary(provider_code) | {
            "feature_month": str(row.feature_month),
            "target_month": str(pd.Period(row.feature_month, freq="M") + 1),
        }
        return frame, context

    def list_providers(self) -> list[dict]:
        data = self._load().sort_values("feature_month")
        latest = data.groupby("provider_code", as_index=False).tail(1)
        return [
            {"code": str(row.provider_code), "name": str(row.provider_name),
             "latest_month": str(row.feature_month)}
            for row in latest.itertuples()
        ]

    def latest_feature_month(self, provider_code: str) -> str:
        return self.provider_summary(provider_code)["history_end_month"]

    def history(self, provider_code: str) -> list[dict]:
        data = self._load()
        rows = data[data.provider_code.eq(provider_code)].sort_values("feature_month")
        if rows.empty:
            raise ProviderHistoryError(f"Unknown NHS provider code: {provider_code}")
        return rows[["feature_month", "emergency_admissions", "total_ae_attendances"]].replace(
            {pd.NA: None, np.nan: None}
        ).to_dict("records")


class HospitalHistoryFeatureBuilder:
    """Build the exported contract from one hospital's own completed months."""

    def __init__(self, feature_schema: dict) -> None:
        self.features = list(feature_schema["features"])

    @staticmethod
    def _rate(numerator: float, denominator: float) -> float:
        return float(numerator / denominator) if denominator else np.nan

    def build(self, hospital_identifier: str, hospital_name: str, history: list[dict]):
        data = pd.DataFrame(history).copy()
        data["period"] = data["month"].map(lambda value: pd.Period(value, freq="M"))
        data = data.sort_values("period").reset_index(drop=True)
        if len(data) < 13:
            raise ProviderHistoryError("At least 13 consecutive completed months are required.")
        expected = list(pd.period_range(data.period.iloc[0], data.period.iloc[-1], freq="M"))
        if data.period.tolist() != expected:
            raise ProviderHistoryError("Hospital history must be consecutive and contain no duplicate months.")
        current = data.iloc[-1]
        period = current.period
        admissions = data.emergency_admissions.astype(float)
        attendances = data.total_ae_attendances.astype(float)
        under_four = data.attendances_under_4_hours.astype(float)
        waits = data.decision_to_admit_waits_over_4_hours.astype(float)
        values = {
            "provider_code": hospital_identifier.upper(),
            "total_ae_attendances": float(current.total_ae_attendances),
            "attendances_under_4_hours": float(current.attendances_under_4_hours),
            "decision_to_admit_waits_over_4_hours": float(current.decision_to_admit_waits_over_4_hours),
            "year": period.year,
            "month": period.month,
            "quarter": period.quarter,
            "days_in_month": period.days_in_month,
            "winter_flag": int(period.month in (11, 12, 1, 2, 3)),
            "month_sin": float(np.sin(2 * np.pi * period.month / 12)),
            "month_cos": float(np.cos(2 * np.pi * period.month / 12)),
            "covid_disruption_period": int(pd.Period("2020-03", "M") <= period <= pd.Period("2021-06", "M")),
        }
        for lag in (1, 2, 3, 6, 12):
            values[f"emergency_admissions_lag_{lag}"] = float(admissions.iloc[-1 - lag])
            values[f"total_ae_attendances_lag_{lag}"] = float(attendances.iloc[-1 - lag])
        for lag in (1, 3, 12):
            values[f"waits_over_4_hours_lag_{lag}"] = float(waits.iloc[-1 - lag])
        for lag in (1, 3):
            index = -1 - lag
            values[f"four_hour_performance_rate_lag_{lag}"] = self._rate(under_four.iloc[index], attendances.iloc[index])
            values[f"admission_conversion_rate_lag_{lag}"] = self._rate(admissions.iloc[index], attendances.iloc[index])
        previous = data.iloc[:-1]
        for window in (3, 6, 12):
            values[f"admissions_rolling_mean_{window}"] = float(previous.emergency_admissions.tail(window).mean())
            values[f"admissions_rolling_std_{window}"] = float(previous.emergency_admissions.tail(window).std())
            values[f"attendances_rolling_mean_{window}"] = float(previous.total_ae_attendances.tail(window).mean())
        for lag in (1, 3):
            values[f"admissions_change_{lag}"] = float(admissions.iloc[-1] - admissions.iloc[-1 - lag])
        for series, prefix in ((admissions, "admissions"), (attendances, "attendance")):
            for lag in (1, 12):
                old = float(series.iloc[-1 - lag])
                growth = self._rate(float(series.iloc[-1]) - old, old)
                values[f"{prefix}_growth_rate_{lag}"] = float(np.clip(growth, -5, 5))
        values["provider_historical_mean"] = float(admissions.iloc[:-1].mean())
        values["provider_historical_std"] = float(admissions.iloc[:-1].std())
        values["provider_historical_median"] = float(admissions.iloc[:-1].median())
        missing = [name for name in self.features if name not in values]
        if missing:
            raise FeatureValidationError(f"Missing hospital-derived features: {missing}")
        frame = pd.DataFrame([[values[name] for name in self.features]], columns=self.features)
        return frame.replace({pd.NA: np.nan}), {
            "code": hospital_identifier.upper(), "name": hospital_name,
            "feature_month": str(period), "target_month": str(period + 1),
            "history_start_month": str(data.period.iloc[0]),
            "history_end_month": str(period), "months": len(data),
        }
