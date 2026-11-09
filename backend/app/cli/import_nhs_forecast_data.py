from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.db.base import Base
from app.db.models import Provider, ProviderMonthlyMetric
from app.db.session import SessionLocal, engine


def import_data(data_dir: Path, dry_run: bool = False, batch_size: int = 1000) -> dict:
    panel_path = data_dir / "provider_month_panel.parquet"
    metadata_path = data_dir / "provider_metadata.csv"
    if not panel_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Expected provider_month_panel.parquet and provider_metadata.csv")
    panel = pd.read_parquet(panel_path)
    metadata = pd.read_csv(metadata_path)
    required = {"provider_code", "reporting_month", "emergency_admissions"}
    if missing := required - set(panel.columns):
        raise ValueError(f"Processed panel is missing columns: {sorted(missing)}")
    summary = {"providers": int(panel.provider_code.nunique()), "rows": len(panel), "dry_run": dry_run}
    if dry_run:
        return summary
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        name_col = next((c for c in ("provider_name", "name") if c in metadata.columns), None)
        for code, rows in panel.groupby("provider_code"):
            existing = db.scalar(select(Provider).where(Provider.code == code))
            meta = metadata[metadata.provider_code.eq(code)]
            name = str(meta.iloc[-1][name_col]) if name_col and not meta.empty else str(code)
            if not existing:
                db.add(Provider(code=code, name=name, first_month=str(rows.reporting_month.min()),
                                latest_month=str(rows.reporting_month.max())))
        db.flush()
        for start in range(0, len(panel), batch_size):
            for row in panel.iloc[start:start + batch_size].itertuples():
                key = {"provider_code": row.provider_code, "reporting_month": str(row.reporting_month)}
                item = db.scalar(select(ProviderMonthlyMetric).filter_by(**key))
                values = {
                    "emergency_admissions": getattr(row, "emergency_admissions", None),
                    "total_ae_attendances": getattr(row, "total_ae_attendances", None),
                    "attendances_under_4_hours": getattr(row, "attendances_under_4_hours", None),
                    "waits_over_4_hours": getattr(row, "waits_over_4_hours", None),
                }
                if item:
                    for field, value in values.items():
                        setattr(item, field, None if pd.isna(value) else float(value))
                else:
                    db.add(ProviderMonthlyMetric(**key, **{
                        field: None if pd.isna(value) else float(value)
                        for field, value in values.items()
                    }))
            db.commit()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("dataset/processed/nhs_england_ae"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    print(import_data(args.data_dir, args.dry_run, args.batch_size))
