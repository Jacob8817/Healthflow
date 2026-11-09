# HealthFlow Emergency Admissions Forecasting

This workflow forecasts next-month provider-level emergency admissions using official NHS England monthly A&E statistics.

> This model is intended solely for research and hospital operations capacity-planning demonstrations. It forecasts aggregate provider-level emergency admissions and must not be used for individual patient, clinical, diagnostic, triage or treatment decisions.

```powershell
cd F:\projhosp
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-ml.txt
```

Preview official discovery:

```powershell
python backend\scripts\download_nhs_ae_dataset.py `
    --start-month 2018-04 `
    --end-month latest `
    --dry-run
```

Download/update and preprocess:

```powershell
python backend\scripts\download_nhs_ae_dataset.py `
    --start-month 2018-04 `
    --end-month latest

python backend\scripts\nhs_ae_preprocessing.py
```

Launch:

```powershell
jupyter notebook backend\notebooks\healthflow_main_model_training.ipynb
```

Run descriptive cells first. Enable stages separately and only when ready:

```python
ALLOW_MODEL_TRAINING = True
```

After reviewing validation benchmarks, separately enable tuning:

```python
ALLOW_MODEL_TUNING = True
```

Only after features, model family, parameters, and intervals are final, enable the untouched test evaluation:

```python
ALLOW_FINAL_EVALUATION = True
```

Finally, after reviewing all results, enable export:

```python
ALLOW_MODEL_EXPORT = True
```

Do not enable every stage at once. Validation WAPE is primary; the seasonal-naive baseline must be beaten reliably before preferring complexity. Quick mode verifies code only. The primary analysis retains the COVID-disruption indicator; sensitivity exclusion is not automatically preferred.

Safety check:

```powershell
python backend\scripts\validate_main_model_notebook.py
```

### Additional diagnostic figures

The notebook includes an executed additional-diagnostics section before the limitations. Run that section independently to load the saved model and reproduce seven figures without retraining: feature correlations, prediction/residual plots, monthly totals and errors, provider-month error matrix, validation benchmark matrix, permutation importance, and errors by admission volume. PNG copies are saved in backend/reports/emergency_admissions_forecast/figures/extended_diagnostics. The section checks reproduced MAE and WAPE against saved test metrics and stops if they differ. Its reusable cell definitions are in backend/scripts/notebook_diagnostics.py and are included by the notebook generator.
