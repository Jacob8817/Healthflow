# NHS England Monthly A&E dataset

HealthFlow uses the official [NHS England A&E Attendances and Emergency Admissions collection](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/). Records are monthly provider-level operational statistics; no patient-level data is used.

> This model is intended solely for research and hospital operations capacity-planning demonstrations. It forecasts aggregate provider-level emergency admissions and must not be used for individual patient, clinical, diagnostic, triage or treatment decisions.

## Download and update

The downloader dynamically discovers financial-year archive pages and the latest monthly publication:

```powershell
python backend\scripts\download_nhs_ae_dataset.py `
    --start-month 2018-04 `
    --end-month latest
```

Preview archive pages, selected/rejected duplicates, missing months, and output paths without downloading:

```powershell
python backend\scripts\download_nhs_ae_dataset.py `
    --start-month 2018-04 `
    --end-month latest `
    --dry-run
```

Run the same update command after a new publication. Existing matching parseable files are reused. Add `--force` to redownload them.

Raw files are normalised as `raw/nhs_england_ae/monthly/YYYY/nhs_ae_YYYY_MM.csv`. CSV is preferred; an official XLS/XLSX provider-level fallback is converted to the same canonical CSV layout. The manifest records source page/URL, original filename/format, reporting month, revision status, checksum, size, headers, rejected duplicates, and missing months.

## Schema and provider continuity

Historical files vary in capitalization, punctuation, wording, booked-attendance columns, and spreadsheet header placement. `nhs_ae_preprocessing.py` applies explicit audited mappings and stops if required provider, attendance, wait, or admission semantics cannot be derived. National, regional/system, subtotal, and invalid-code rows are excluded from provider observations.

Provider identity is the official provider code plus reporting month. Codes are never merged because names look similar. Continuity output records first/last month, months present/missing, and name changes. Missing reports are not treated as true zeros.

Processed outputs under `processed/nhs_england_ae/` include the provider panel, forecasting features, provider metadata, national totals, schema mapping, continuity report, and data-quality report. Generated data and manifests are ignored by Git so large/reproducible data and derived operational tables are not committed.

Limitations include reporting revisions, missing months, organisational changes, collection/schema changes, measurement error, COVID disruption, and changing provider footprints.
