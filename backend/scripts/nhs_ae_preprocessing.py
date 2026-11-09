"""Build leakage-safe NHS England provider-month forecasting tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_SEMANTICS = {
    "provider_code", "provider_name", "reporting_period", "ae_type",
    "total_ae_attendances", "attendances_under_4_hours",
    "emergency_admissions", "decision_to_admit_waits_over_4_hours",
}
COVID_START = pd.Period("2020-03", freq="M")
COVID_END = pd.Period("2021-06", freq="M")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalise_column(value: object) -> str:
    text = str(value).strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


ALIASES = {
    "period": "reporting_period",
    "code": "provider_code",
    "org_code": "provider_code",
    "organisation_code": "provider_code",
    "name": "provider_name",
    "org_name": "provider_name",
    "organisation_name": "provider_name",
    "a_and_e_attendances_type_1": "attendances_type_1",
    "number_of_a_and_e_attendances_type_1": "attendances_type_1",
    "a_and_e_attendances_type_2": "attendances_type_2",
    "number_of_a_and_e_attendances_type_2": "attendances_type_2",
    "a_and_e_attendances_other_a_and_e_department": "attendances_type_3",
    "number_of_a_and_e_attendances_other_a_and_e_department": "attendances_type_3",
    "type_1_departments_major_a_and_e": "attendances_type_1",
    "type_2_departments_single_specialty": "attendances_type_2",
    "type_3_departments_other_a_and_e_minor_injury_unit": "attendances_type_3",
    "total_attendances": "total_ae_attendances",
    "attendances_over_4hrs_type_1": "over_4_hours_type_1",
    "number_of_attendances_over_4hrs_type_1": "over_4_hours_type_1",
    "attendances_over_4hrs_type_2": "over_4_hours_type_2",
    "number_of_attendances_over_4hrs_type_2": "over_4_hours_type_2",
    "attendances_over_4hrs_other_department": "over_4_hours_type_3",
    "number_of_attendances_over_4hrs_other_a_and_e_department": "over_4_hours_type_3",
    "total_attendances_4_hours": "attendances_over_4_hours",
    "total_attendances_4_hours_1": "attendances_over_4_hours",
    "total_attendances_4_hours_2": "attendances_over_4_hours",
    "total_attendances_4_hours_3": "attendances_over_4_hours",
    "total_attendances_4_hours_4": "attendances_over_4_hours",
    "total_attendances_4_hours_5": "attendances_over_4_hours",
    "patients_who_have_waited_4_12_hs_from_dta_to_admission": "dta_wait_4_to_12_hours",
    "patients_who_have_waited_12_hrs_from_dta_to_admission": "dta_wait_over_12_hours",
    "number_of_patients_spending_4_hours_from_decision_to_admit_to_admission": "dta_wait_over_4_hours",
    "number_of_patients_spending_12_hours_from_decision_to_admit_to_admission": "dta_wait_over_12_hours",
    "emergency_admissions_via_a_and_e_type_1": "admissions_type_1",
    "emergency_admissions_via_type_1_a_and_e": "admissions_type_1",
    "emergency_admissions_via_a_and_e_type_2": "admissions_type_2",
    "emergency_admissions_via_type_2_a_and_e": "admissions_type_2",
    "emergency_admissions_via_a_and_e_other_a_and_e_department": "admissions_type_3",
    "emergency_admissions_via_type_3_and_4_a_and_e": "admissions_type_3",
    "other_emergency_admissions": "other_emergency_admissions",
    "other_emergency_admissions_i_e_not_via_a_and_e": "other_emergency_admissions",
    "total_emergency_admissions": "emergency_admissions",
}


def semantic_for(normalised: str) -> str | None:
    if normalised in ALIASES:
        return ALIASES[normalised]
    if "total_attendances" in normalised and "4_hour" not in normalised:
        return "total_ae_attendances"
    if "total_emergency_admissions" in normalised:
        return "emergency_admissions"
    return None


def read_month(record: dict, root: Path) -> tuple[pd.DataFrame, list[dict]]:
    path = root / record["local_relative_path"]
    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    mapping, renamed = [], {}
    for column in frame.columns:
        normalised = normalise_column(column)
        original_lower = str(column).strip().lower()
        if "total attendances < 4" in original_lower:
            semantic = "attendances_under_4_hours"
        elif "total attendances > 4" in original_lower:
            semantic = "attendances_over_4_hours"
        elif "total emergency admissions via" in original_lower:
            semantic = "admissions_via_ae_total"
        else:
            semantic = semantic_for(normalised)
        renamed[column] = semantic or normalised
        mapping.append({
            "reporting_month": record["reporting_month"],
            "source_file": record["local_relative_path"],
            "original_column": str(column),
            "normalised_column": normalised,
            "semantic_field": semantic or "",
            "mapping_status": "mapped" if semantic else "unmapped_nonrequired",
        })
    frame = frame.rename(columns=renamed)
    duplicates = frame.columns[frame.columns.duplicated()].tolist()
    if duplicates:
        raise ValueError(f"{path} maps multiple columns to the same field: {duplicates}")
    if not {"provider_code", "provider_name"}.issubset(frame.columns):
        raise ValueError(f"{path} cannot map provider code/name; headers={list(frame.columns)}")
    for column in frame.columns:
        if column not in {"provider_code", "provider_name", "reporting_period"}:
            frame[column] = pd.to_numeric(
                frame[column].astype("string").str.replace(",", "", regex=False)
                .replace({"-": pd.NA, "": pd.NA}), errors="coerce"
            )
    frame["reporting_month"] = pd.Period(record["reporting_month"], freq="M")
    frame["source_file"] = record["local_relative_path"]
    frame["source_url"] = record["source_url"]
    return frame, mapping


def row_total(frame: pd.DataFrame, direct: str, components: list[str]) -> pd.Series:
    if direct in frame:
        direct_values = frame[direct]
    else:
        direct_values = pd.Series(np.nan, index=frame.index)
    available = [column for column in components if column in frame]
    component_values = (
        frame[available].sum(axis=1, min_count=1)
        if available else pd.Series(np.nan, index=frame.index)
    )
    return direct_values.combine_first(component_values)


def normalise_month(record: dict, root: Path) -> tuple[pd.DataFrame, list[dict]]:
    frame, mappings = read_month(record, root)
    frame["total_ae_attendances"] = row_total(
        frame, "total_ae_attendances",
        ["attendances_type_1", "attendances_type_2", "attendances_type_3"],
    )
    frame["attendances_over_4_hours"] = row_total(
        frame, "attendances_over_4_hours",
        ["over_4_hours_type_1", "over_4_hours_type_2", "over_4_hours_type_3"],
    )
    calculated_under_four = (
        frame["total_ae_attendances"] - frame["attendances_over_4_hours"]
    )
    if "attendances_under_4_hours" in frame:
        frame["attendances_under_4_hours"] = frame[
            "attendances_under_4_hours"
        ].combine_first(calculated_under_four)
    else:
        frame["attendances_under_4_hours"] = calculated_under_four
    frame["emergency_admissions"] = row_total(
        frame, "emergency_admissions",
        ["admissions_type_1", "admissions_type_2", "admissions_type_3",
         "other_emergency_admissions"],
    )
    frame["decision_to_admit_waits_over_4_hours"] = row_total(
        frame, "dta_wait_over_4_hours",
        ["dta_wait_4_to_12_hours", "dta_wait_over_12_hours"],
    )
    frame["ae_type"] = "All types"
    required = [
        "provider_code", "provider_name", "reporting_month", "ae_type",
        "total_ae_attendances", "attendances_under_4_hours",
        "emergency_admissions", "decision_to_admit_waits_over_4_hours",
        "source_file", "source_url",
    ]
    missing = [column for column in required if column not in frame]
    if missing or frame["emergency_admissions"].isna().all():
        raise ValueError(
            f"Required semantic mapping failed for {record['local_relative_path']}; "
            f"missing={missing}, headers={list(frame.columns)}"
        )
    return frame[required], mappings


def classify_rows(frame: pd.DataFrame) -> pd.Series:
    code = frame.provider_code.astype("string").str.strip()
    name = frame.provider_name.astype("string").str.strip().str.lower()
    national = name.str.fullmatch(r"(?:england|total)", na=False) | code.str.fullmatch(
        r"total", case=False, na=False
    ) | (
        code.isin(["-", "", "<NA>"]) & name.str.contains("england", na=False)
    )
    aggregate = name.str.contains(
        r"\b(?:total|region|integrated care|commissioning|system|stp)\b", regex=True, na=False
    )
    valid_code = code.str.fullmatch(r"[A-Z0-9]{3,8}", na=False)
    return np.select(
        [national, aggregate, ~valid_code],
        ["national_total", "regional_or_system_total", "invalid"],
        default="provider",
    )


def safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator.ne(0)))


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    data = panel.sort_values(["provider_code", "reporting_month"]).copy()
    month_timestamp = data.reporting_month.dt.to_timestamp()
    data["feature_month"] = data.reporting_month.astype(str)
    data["year"] = month_timestamp.dt.year
    data["month"] = month_timestamp.dt.month
    data["quarter"] = month_timestamp.dt.quarter
    data["financial_year"] = np.where(
        data.month >= 4, data.year.astype(str) + "-" + (data.year + 1).astype(str).str[-2:],
        (data.year - 1).astype(str) + "-" + data.year.astype(str).str[-2:],
    )
    data["days_in_month"] = month_timestamp.dt.days_in_month
    data["winter_flag"] = data.month.isin([11, 12, 1, 2, 3]).astype("int8")
    data["month_sin"] = np.sin(2 * np.pi * data.month / 12)
    data["month_cos"] = np.cos(2 * np.pi * data.month / 12)
    data["covid_disruption_period"] = data.reporting_month.between(
        COVID_START, COVID_END
    ).astype("int8")
    grouped = data.groupby("provider_code", sort=False)
    for base, prefix in (
        ("emergency_admissions", "emergency_admissions"),
        ("total_ae_attendances", "total_ae_attendances"),
    ):
        for lag in (1, 2, 3, 6, 12):
            data[f"{prefix}_lag_{lag}"] = grouped[base].shift(lag)
    for lag in (1, 3, 12):
        data[f"waits_over_4_hours_lag_{lag}"] = grouped[
            "decision_to_admit_waits_over_4_hours"
        ].shift(lag)
    four_hour_rate = safe_rate(
        data.attendances_under_4_hours, data.total_ae_attendances
    )
    conversion_rate = safe_rate(data.emergency_admissions, data.total_ae_attendances)
    for lag in (1, 3):
        data[f"four_hour_performance_rate_lag_{lag}"] = (
            four_hour_rate.groupby(data.provider_code).shift(lag)
        )
        data[f"admission_conversion_rate_lag_{lag}"] = (
            conversion_rate.groupby(data.provider_code).shift(lag)
        )
    for window in (3, 6, 12):
        data[f"admissions_rolling_mean_{window}"] = grouped[
            "emergency_admissions"
        ].transform(lambda values, w=window: values.shift(1).rolling(w).mean())
        data[f"admissions_rolling_std_{window}"] = grouped[
            "emergency_admissions"
        ].transform(lambda values, w=window: values.shift(1).rolling(w).std())
        data[f"attendances_rolling_mean_{window}"] = grouped[
            "total_ae_attendances"
        ].transform(lambda values, w=window: values.shift(1).rolling(w).mean())
    for lag in (1, 3):
        data[f"admissions_change_{lag}"] = (
            data.emergency_admissions - grouped.emergency_admissions.shift(lag)
        )
    for base, prefix in (
        ("emergency_admissions", "admissions"),
        ("total_ae_attendances", "attendance"),
    ):
        for lag in (1, 12):
            previous = grouped[base].shift(lag)
            data[f"{prefix}_growth_rate_{lag}"] = safe_rate(
                data[base] - previous, previous
            ).clip(-5, 5)
    past = grouped.emergency_admissions.shift(1)
    expanding = past.groupby(data.provider_code)
    data["provider_historical_mean"] = expanding.expanding().mean().reset_index(level=0, drop=True)
    data["provider_historical_std"] = expanding.expanding().std().reset_index(level=0, drop=True)
    data["provider_historical_median"] = expanding.expanding().median().reset_index(level=0, drop=True)
    for horizon in (1, 2, 3):
        data[f"target_emergency_admissions_h{horizon}"] = grouped[
            "emergency_admissions"
        ].shift(-horizon)
    data["target_month"] = (
        data.reporting_month + 1
    ).astype(str)
    return data


def continuity_report(panel: pd.DataFrame) -> pd.DataFrame:
    first, last = panel.reporting_month.min(), panel.reporting_month.max()
    expected = len(pd.period_range(first, last, freq="M"))
    return panel.groupby("provider_code").agg(
        provider_name=("provider_name", "last"),
        first_reporting_month=("reporting_month", lambda values: str(values.min())),
        last_reporting_month=("reporting_month", lambda values: str(values.max())),
        months_present=("reporting_month", "nunique"),
        provider_name_changes=("provider_name", "nunique"),
    ).assign(
        months_missing=lambda value: expected - value.months_present,
        missing_month_fraction=lambda value: value.months_missing / expected,
    ).reset_index()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-history-months", type=int, default=24)
    parser.add_argument("--maximum-missing-month-fraction", type=float, default=0.20)
    args = parser.parse_args()
    root = repository_root()
    manifest_path = root / "backend/dataset/manifests/nhs_ae_download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames, mappings = [], []
    for record in manifest["files"]:
        frame, audit = normalise_month(record, root)
        frames.append(frame)
        mappings.extend(audit)
    raw = pd.concat(frames, ignore_index=True)
    raw["row_class"] = classify_rows(raw)
    national = raw[raw.row_class.eq("national_total")].copy()
    providers = raw[raw.row_class.eq("provider")].copy()
    providers["provider_code"] = providers.provider_code.astype("string").str.strip()
    providers["provider_name"] = providers.provider_name.astype("string").str.strip()
    if providers.duplicated(["provider_code", "reporting_month"]).any():
        duplicated = providers.loc[
            providers.duplicated(["provider_code", "reporting_month"], keep=False),
            ["provider_code", "reporting_month", "provider_name"],
        ]
        raise ValueError(f"Duplicate provider-month records found:\n{duplicated.head(30)}")
    continuity = continuity_report(providers)
    eligible_codes = continuity.loc[
        (continuity.months_present >= args.minimum_history_months)
        & (continuity.missing_month_fraction <= args.maximum_missing_month_fraction),
        "provider_code",
    ]
    panel = providers[providers.provider_code.isin(eligible_codes)].copy()
    features = add_features(panel)
    target_period = pd.PeriodIndex(features.target_month, freq="M")
    features["split"] = np.select(
        [
            target_period <= pd.Period("2023-12", freq="M"),
            (target_period >= pd.Period("2024-01", freq="M"))
            & (target_period <= pd.Period("2024-12", freq="M")),
            target_period >= pd.Period("2025-01", freq="M"),
        ],
        ["train", "validation", "test"],
        default="unassigned",
    )
    output = root / "backend/dataset/processed/nhs_england_ae"
    output.mkdir(parents=True, exist_ok=True)
    panel.assign(reporting_month=panel.reporting_month.astype(str)).to_parquet(
        output / "provider_month_panel.parquet", index=False
    )
    features.assign(reporting_month=features.reporting_month.astype(str)).to_parquet(
        output / "forecasting_features.parquet", index=False
    )
    continuity.to_csv(output / "provider_metadata.csv", index=False)
    continuity.to_csv(output / "provider_continuity_report.csv", index=False)
    national.groupby("reporting_month", as_index=False)[
        ["total_ae_attendances", "emergency_admissions"]
    ].sum().assign(reporting_month=lambda value: value.reporting_month.astype(str)).to_csv(
        output / "national_monthly_totals.csv", index=False
    )
    mapping_frame = pd.DataFrame(mappings)
    mapping_frame.to_csv(output / "schema_mapping.csv", index=False)
    quality = {
        "raw_rows": len(raw), "provider_rows": len(providers),
        "eligible_provider_rows": len(panel),
        "negative_count_rows": int((panel[["total_ae_attendances", "emergency_admissions"]] < 0).any(axis=1).sum()),
        "duplicate_provider_months": int(panel.duplicated(["provider_code", "reporting_month"]).sum()),
        "missing_months": manifest["missing_months"],
        "excluded_row_classes": raw.row_class.value_counts().to_dict(),
        "warnings": manifest["warnings"],
    }
    (output / "data_quality_report.json").write_text(
        json.dumps(quality, indent=2, default=str) + "\n", encoding="utf-8"
    )
    processed_manifest = {
        "source_file_hashes": {
            record["local_relative_path"]: record["sha256"] for record in manifest["files"]
        },
        "date_range": [str(panel.reporting_month.min()), str(panel.reporting_month.max())],
        "number_of_monthly_files": len(manifest["files"]),
        "provider_count": int(panel.provider_code.nunique()),
        "provider_month_row_count": len(panel),
        "feature_names": [column for column in features if column not in {
            "provider_name", "target_emergency_admissions_h1",
            "target_emergency_admissions_h2", "target_emergency_admissions_h3",
        }],
        "target_definition": "provider-wise next-month emergency admissions (h1)",
        "lag_definitions": "provider-wise shifts of 1,2,3,6,12 months",
        "rolling_window_definitions": "shift(1) then rolling 3,6,12 months",
        "missing_month_rules": "No zero filling; gaps remain missing for pipeline imputation",
        "provider_eligibility_rules": {
            "minimum_history_months": args.minimum_history_months,
            "maximum_missing_month_fraction": args.maximum_missing_month_fraction,
        },
        "schema_mappings": mapping_frame.mapping_status.value_counts().to_dict(),
        "data_quality_warnings": quality["warnings"],
        "creation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    destination = root / "backend/dataset/manifests/nhs_ae_processed_manifest.json"
    destination.write_text(
        json.dumps(processed_manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "files": len(manifest["files"]), "providers": int(panel.provider_code.nunique()),
        "provider_month_rows": len(panel), "feature_rows": len(features),
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
