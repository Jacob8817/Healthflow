"""Generate the unexecuted NHS England forecasting notebook."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend/notebooks/healthflow_main_model_training.ipynb"


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def code(source, tag=None):
    metadata = {"tags": [tag]} if tag else {}
    return {"cell_type": "code", "execution_count": None, "metadata": metadata,
            "outputs": [], "source": source}


DISCLAIMER = (
    "This model is intended solely for research and hospital operations "
    "capacity-planning demonstrations. It forecasts aggregate provider-level "
    "emergency admissions and must not be used for individual patient, clinical, "
    "diagnostic, triage or treatment decisions."
)
cells = [
md(f"""# HealthFlow Main Model
## NHS England Emergency Admissions Forecasting

A provider-level time-series workflow forecasting next-month total emergency admissions from official historical NHS England monthly A&E activity. Optional direct horizons of two and three months are prepared, while horizon one controls selection and deployment.

Operational uses include capacity, bed-demand, staffing, resource, scenario, and operational-risk planning. It is not an individual-patient model or an autonomous hospital decision system.

> **{DISCLAIMER}**

Codex downloaded, validated, normalised, audited, and feature-engineered the data, but did not train, tune, evaluate, forecast with, select, or export any model."""),
md("## 1 — Configuration"),
code("""from pathlib import Path
import os, sys, platform, json, time, importlib, hashlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd

RANDOM_SEED = 42
BOOTSTRAP_SEED = 42
ALLOW_MODEL_TRAINING = False
ALLOW_MODEL_TUNING = False
ALLOW_FINAL_EVALUATION = False
ALLOW_MODEL_EXPORT = False
BENCHMARK_MODE = "standard"  # quick, standard, full
N_JOBS = -1
TUNING_ITERATIONS = 25
TRAIN_TARGET_END = "2023-12"
VALIDATION_TARGET_START = "2024-01"
VALIDATION_TARGET_END = "2024-12"
TEST_TARGET_START = "2025-01"
TEST_TARGET_END = "latest"
MINIMUM_HISTORY_MONTHS = 24
MAXIMUM_MISSING_MONTH_FRACTION = .20
EXCLUDE_COVID_SENSITIVITY = False

def find_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "backend").is_dir():
            return candidate
    raise FileNotFoundError("Could not find repository root containing backend/.")

REPOSITORY_ROOT = find_root(Path.cwd())
BACKEND = REPOSITORY_ROOT / "backend"
RAW_DIR = BACKEND / "dataset/raw/nhs_england_ae/monthly"
PROCESSED_DIR = BACKEND / "dataset/processed/nhs_england_ae"
MANIFEST_DIR = BACKEND / "dataset/manifests"
ARTIFACT_DIR = BACKEND / "model_artifacts/emergency_admissions_forecast"
FIGURES_DIR = BACKEND / "reports/emergency_admissions_forecast/figures"
METRICS_DIR = BACKEND / "reports/emergency_admissions_forecast/metrics"
print("NHS England provider-month forecasting workflow:", REPOSITORY_ROOT)
"""),
md("## 2 — Environment validation\n\nCPU is the default; no GPU is required."),
code("""import importlib.metadata as metadata
packages = ["pandas","pyarrow","numpy","scipy","scikit-learn","joblib","matplotlib",
 "jupyter","ipykernel","nbformat","nbclient","requests","tqdm","beautifulsoup4",
 "lxml","openpyxl","xlrd","xgboost","lightgbm","catboost","statsmodels","psutil"]
versions={}
for package in packages:
    try: versions[package]=metadata.version(package)
    except metadata.PackageNotFoundError: versions[package]="NOT INSTALLED"
try:
    import psutil
    ram_gib=round(psutil.virtual_memory().total/2**30,1)
except ImportError: ram_gib="unavailable"
print({"python":sys.version.split()[0],"os":platform.platform(),"cpus":os.cpu_count(),
       "ram_gib":ram_gib,"paths":{"raw":str(RAW_DIR),"processed":str(PROCESSED_DIR)}})
display(pd.Series(versions,name="version"))
for package in ("xgboost","lightgbm","catboost","statsmodels"):
    print(package, versions[package] != "NOT INSTALLED")
"""),
md("## 3 — Dataset discovery and manifest audit"),
code("""download_manifest_path=MANIFEST_DIR/"nhs_ae_download_manifest.json"
if not download_manifest_path.exists():
    raise FileNotFoundError("Run: python backend/scripts/download_nhs_ae_dataset.py --start-month 2018-04 --end-month latest")
download_manifest=json.loads(download_manifest_path.read_text(encoding="utf-8"))
manifest_files=pd.DataFrame(download_manifest["files"])
display({"requested_range":[download_manifest["requested_start_month"],download_manifest["requested_end_month"]],
 "latest":download_manifest["latest_month_discovered"],"files":len(manifest_files),
 "missing":download_manifest["missing_months"],"revised":int(manifest_files.revised.sum()),
 "duplicates_rejected":len(download_manifest["duplicate_candidates_rejected"])})
display(manifest_files[["reporting_month","financial_year","revised","sha256",
                         "local_relative_path","source_url"]])
"""),
md("## 4 — Raw schema audit\n\nMappings are explicit and file-specific. Unmapped required semantics stop preprocessing; no missing target is filled with zero."),
code("""schema_mapping=pd.read_csv(PROCESSED_DIR/"schema_mapping.csv")
schema_mapping["year"]=schema_mapping.reporting_month.str[:4]
display(schema_mapping.groupby(["year","mapping_status"]).size().unstack(fill_value=0))
display(schema_mapping[["reporting_month","source_file","original_column",
 "normalised_column","semantic_field","mapping_status"]])
display(schema_mapping[schema_mapping.mapping_status.ne("mapped")]
        .groupby("year").original_column.unique())
"""),
md("## 5 — Normalised provider panel, filtering, A&E aggregation, and reconciliation\n\nThe preprocessing script separates national, regional/system, and invalid rows; keeps valid provider codes only; uses official all-type totals when present and otherwise sums mutually exclusive Type 1/2/3 components. Quarterly aggregates are excluded at discovery. Provider names are display-only."),
code("""panel=pd.read_parquet(PROCESSED_DIR/"provider_month_panel.parquet")
panel["reporting_month"]=pd.PeriodIndex(panel.reporting_month,freq="M")
continuity=pd.read_csv(PROCESSED_DIR/"provider_continuity_report.csv")
national=pd.read_csv(PROCESSED_DIR/"national_monthly_totals.csv")
quality=json.loads((PROCESSED_DIR/"data_quality_report.json").read_text())
print(panel.shape,panel.provider_code.nunique(),panel.reporting_month.min(),panel.reporting_month.max())
assert not panel.duplicated(["provider_code","reporting_month"]).any()
assert panel.provider_code.notna().all()
display(quality); display(continuity.describe(include="all"))
"""),
md("## 6 — Data-quality and provider-continuity audit\n\nOutliers are reported, not automatically deleted. Provider-code changes are never inferred from name similarity. Missing months remain missing rather than becoming false zeros."),
code("""counts=["total_ae_attendances","attendances_under_4_hours","emergency_admissions",
        "decision_to_admit_waits_over_4_hours"]
quality_table=pd.DataFrame({
 "missing":panel[counts].isna().sum(),"negative":(panel[counts]<0).sum(),
 "minimum":panel[counts].min(),"maximum":panel[counts].max()})
display(quality_table)
display(continuity.sort_values(["months_missing","provider_name_changes"],ascending=False).head(30))
changes=panel.sort_values(["provider_code","reporting_month"]).groupby("provider_code").emergency_admissions.pct_change(fill_method=None)
display(panel.loc[changes.abs().nlargest(30).index,
 ["provider_code","provider_name","reporting_month","emergency_admissions"]])
"""),
md("## 7 — Exploratory analysis"),
code("""import matplotlib.pyplot as plt
monthly=panel.groupby("reporting_month")[counts].sum()
monthly.index=monthly.index.to_timestamp()
monthly[["emergency_admissions","total_ae_attendances"]].plot(subplots=True,figsize=(12,7),title=["National emergency admissions","National A&E attendances"]); plt.show()
(monthly.emergency_admissions/monthly.total_ae_attendances).plot(title="Admission conversion rate"); plt.show()
seasonal=panel.assign(month=panel.reporting_month.dt.month).groupby("month").emergency_admissions.mean()
plt.bar(seasonal.index.astype(int),seasonal.values);plt.title("Seasonal provider mean");plt.xlabel("Month");plt.show()
panel.emergency_admissions.plot.hist(bins=50,title="Provider-month admissions distribution"); plt.show()
continuity.months_present.plot.hist(bins=30,title="Provider history length"); plt.show()
missingness=panel[counts].isna().mean()
plt.bar(range(len(missingness)),missingness.values);plt.xticks(range(len(missingness)),missingness.index,rotation=45,ha="right");plt.title("Missingness");plt.tight_layout();plt.show()
period=np.select([panel.reporting_month<pd.Period("2020-03"),panel.reporting_month<=pd.Period("2021-06")],["pre-COVID","disruption"],default="post-disruption")
display(panel.assign(period=period).groupby("period")[counts].agg(["mean","median"]))
display(panel.groupby(["provider_code","provider_name"]).emergency_admissions.mean().nlargest(20))
yoy=monthly.emergency_admissions.pct_change(12); yoy.plot(title="National year-over-year admissions change"); plt.show()
plt.scatter(panel.attendances_under_4_hours/panel.total_ae_attendances,panel.emergency_admissions,s=3,alpha=.2)
plt.xlabel("Four-hour performance"); plt.ylabel("Emergency admissions"); plt.show()
"""),
md("## 8 — Leakage-safe forecasting features and targets\n\nAll lags are provider-wise. Rolling and historical provider statistics use `shift(1)` before aggregation. Targets h1/h2/h3 use chronological negative shifts. COVID disruption is retained in the primary analysis; sensitivity exclusion is configurable and never automatically preferred."),
code("""features=pd.read_parquet(PROCESSED_DIR/"forecasting_features.parquet")
features["reporting_month"]=pd.PeriodIndex(features.reporting_month,freq="M")
TARGET="target_emergency_admissions_h1"
OPTIONAL_TARGETS=["target_emergency_admissions_h2","target_emergency_admissions_h3"]
TARGETS=[TARGET,*OPTIONAL_TARGETS]
NON_FEATURES={"provider_name","reporting_month","feature_month","target_month","split",
              "emergency_admissions",*TARGETS,"source_file","source_url","ae_type",
              "row_class","financial_year"}
MODEL_FEATURES=[column for column in features.columns if column not in NON_FEATURES]
assert TARGET not in MODEL_FEATURES
assert not any(column.startswith("target_") for column in MODEL_FEATURES)
assert all(("rolling" not in c) or c.startswith(("admissions_rolling","attendances_rolling")) for c in MODEL_FEATURES)
display(pd.Series(MODEL_FEATURES,name="feature"))
display(features[TARGETS].describe())
"""),
md("## 9 — Chronological split and rolling-origin definitions"),
code("""target_period=pd.PeriodIndex(features.target_month,freq="M")
features["split"]=np.select([
 target_period<=pd.Period(TRAIN_TARGET_END),
 (target_period>=pd.Period(VALIDATION_TARGET_START))&(target_period<=pd.Period(VALIDATION_TARGET_END)),
 target_period>=pd.Period(TEST_TARGET_START)],["train","validation","test"],default="unassigned")
if EXCLUDE_COVID_SENSITIVITY:
    features=features[features.covid_disruption_period.eq(0)].copy()
def split_report(frame):
    return frame.groupby("split").agg(feature_start=("feature_month","min"),feature_end=("feature_month","max"),
      target_start=("target_month","min"),target_end=("target_month","max"),
      providers=("provider_code","nunique"),rows=("provider_code","size"),
      missing_target=(TARGET,lambda x:x.isna().sum()),target_mean=(TARGET,"mean"),
      target_median=(TARGET,"median"),target_std=(TARGET,"std"))
display(split_report(features))
train=features[features.split.eq("train") & features[TARGET].notna()].copy()
validation=features[features.split.eq("validation") & features[TARGET].notna()].copy()
test=features[features.split.eq("test") & features[TARGET].notna()].copy()
assert pd.PeriodIndex(train.target_month,freq="M").max()<pd.PeriodIndex(validation.target_month,freq="M").min()
def rolling_origin_folds(frame,min_train_months=36,validation_months=3):
    periods=sorted(pd.PeriodIndex(frame.target_month,freq="M").unique())
    folds=[]
    for stop in range(min_train_months,len(periods)-validation_months+1,validation_months):
        train_end=periods[stop-1]; valid=periods[stop:stop+validation_months]
        folds.append((frame.index[pd.PeriodIndex(frame.target_month,freq="M")<=train_end],
                      frame.index[pd.PeriodIndex(frame.target_month,freq="M").isin(valid)]))
    return folds
ROLLING_FOLDS=rolling_origin_folds(train)
display(pd.DataFrame([{"fold":i+1,"train_end":train.loc[a,"target_month"].max(),
 "validation_start":train.loc[b,"target_month"].min(),"validation_end":train.loc[b,"target_month"].max()}
 for i,(a,b) in enumerate(ROLLING_FOLDS)]))
"""),
md("## 10 — Baselines and model pipelines\n\nCounts remain continuous and non-negative. Raw predictions are preserved; clipped predictions are used for operational reporting, with negative counts reported."),
code("""from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.base import BaseEstimator,RegressorMixin
from sklearn.linear_model import LinearRegression,Ridge,ElasticNet
from sklearn.ensemble import RandomForestRegressor,ExtraTreesRegressor,GradientBoostingRegressor,HistGradientBoostingRegressor
class CatBoostRegressorAdapter(RegressorMixin,BaseEstimator):
    def __init__(self,iterations=400,depth=6,learning_rate=.04,verbose=False,
                 thread_count=-1,random_seed=42):
        self.iterations=iterations;self.depth=depth;self.learning_rate=learning_rate
        self.verbose=verbose;self.thread_count=thread_count;self.random_seed=random_seed
    def fit(self,X,y):
        from catboost import CatBoostRegressor
        self.estimator_=CatBoostRegressor(iterations=self.iterations,depth=self.depth,
          learning_rate=self.learning_rate,verbose=self.verbose,
          thread_count=self.thread_count,random_seed=self.random_seed)
        self.estimator_.fit(X,y)
        self.n_features_in_=X.shape[1]
        return self
    def predict(self,X):
        return self.estimator_.predict(X)
    @property
    def feature_importances_(self):
        return self.estimator_.feature_importances_
NUMERICAL=[c for c in MODEL_FEATURES if c!="provider_code"]; CATEGORICAL=["provider_code"]
def preprocessor(scale=False):
    num=[("impute",SimpleImputer(strategy="median",add_indicator=True))]
    if scale:num.append(("scale",StandardScaler()))
    return ColumnTransformer([("numeric",Pipeline(num),NUMERICAL),
      ("categorical",Pipeline([("impute",SimpleImputer(strategy="most_frequent")),
       ("onehot",OneHotEncoder(handle_unknown="ignore",sparse_output=False))]),CATEGORICAL)])
sizes={"quick":50,"standard":300,"full":800}
if BENCHMARK_MODE not in sizes: raise ValueError("BENCHMARK_MODE must be quick, standard, or full")
n_trees=sizes[BENCHMARK_MODE]
models={"Linear Regression":LinearRegression(),"Ridge Regression":Ridge(alpha=10),
 "Elastic Net":ElasticNet(alpha=.1,l1_ratio=.2,max_iter=5000,random_state=RANDOM_SEED),
 "Random Forest":RandomForestRegressor(n_estimators=n_trees,min_samples_leaf=3,n_jobs=N_JOBS,random_state=RANDOM_SEED),
 "Extra Trees":ExtraTreesRegressor(n_estimators=n_trees,min_samples_leaf=3,n_jobs=N_JOBS,random_state=RANDOM_SEED),
 "Gradient Boosting":GradientBoostingRegressor(n_estimators=200,learning_rate=.04,random_state=RANDOM_SEED),
 "Histogram Gradient Boosting":HistGradientBoostingRegressor(max_iter=250,learning_rate=.05,random_state=RANDOM_SEED)}
optional=[("XGBoost","xgboost","XGBRegressor",{"n_estimators":400,"learning_rate":.04,"n_jobs":N_JOBS,"random_state":RANDOM_SEED}),
 ("LightGBM","lightgbm","LGBMRegressor",{"n_estimators":400,"learning_rate":.04,"verbosity":-1,"n_jobs":N_JOBS,"random_state":RANDOM_SEED})]
availability={}
for name,module,cls_name,params in optional:
    try: models[name]=getattr(importlib.import_module(module),cls_name)(**params); availability[name]="available"
    except ImportError: availability[name]=f"unavailable; pip install -r {BACKEND/'requirements-ml.txt'}"
try:
    importlib.import_module("catboost")
    models["CatBoost"]=CatBoostRegressorAdapter(
      iterations=400,learning_rate=.04,verbose=False,
      thread_count=N_JOBS,random_seed=RANDOM_SEED)
    availability["CatBoost"]="available via scikit-learn compatibility adapter"
except ImportError:
    availability["CatBoost"]=f"unavailable; pip install -r {BACKEND/'requirements-ml.txt'}"
display(pd.Series(availability))
def baseline_predictions(frame):
    return {"Last-value naive":frame.emergency_admissions_lag_1,
      "Seasonal naive":frame.emergency_admissions_lag_12,
      "Three-month moving average":frame.admissions_rolling_mean_3,
      "Twelve-month moving average":frame.admissions_rolling_mean_12}
"""),
md("## 11 — Initial benchmarking"),
code("""assert ALLOW_MODEL_TRAINING, (
    "Training is disabled. Manually set ALLOW_MODEL_TRAINING=True "
    "before executing this cell."
)
from sklearn.base import clone
X_train,y_train=train[MODEL_FEATURES],train[TARGET]
X_validation,y_validation=validation[MODEL_FEATURES],validation[TARGET]
fit_train=train
if BENCHMARK_MODE=="quick":
    chosen=np.random.default_rng(RANDOM_SEED).choice(train.provider_code.unique(),
      min(30,train.provider_code.nunique()),replace=False)
    fit_train=train[train.provider_code.isin(chosen)]
fitted_models={}; training_log={}; failures={}
for name,estimator in models.items():
    pipeline=Pipeline([("preprocess",preprocessor(name in {"Linear Regression","Ridge Regression","Elastic Net"})),
                       ("model",clone(estimator))])
    try:
        started=time.perf_counter(); pipeline.fit(fit_train[MODEL_FEATURES],fit_train[TARGET])
        training_log[name]={"training_seconds":time.perf_counter()-started,
                            "parameters":pipeline.get_params()}
        fitted_models[name]=pipeline
    except Exception as exc: failures[name]=repr(exc)
display(training_log); display(failures)
if not fitted_models:
    raise RuntimeError(
        "Every machine-learning model failed. Review the displayed failures "
        "before running validation or tuning."
    )
""","manual_training"),
md("## 12 — Validation metrics, outputs, and intervals"),
code("""assert ALLOW_MODEL_TRAINING, (
    "Training is disabled. Manually set ALLOW_MODEL_TRAINING=True "
    "before executing this cell."
)
from sklearn.metrics import mean_absolute_error,median_absolute_error,mean_squared_error,mean_squared_log_error,r2_score
if not fitted_models:
    raise RuntimeError(
        "No fitted ML models are available. Rerun the manual training cell "
        "and resolve its displayed failures first."
    )
def metrics(y,raw,seasonal,scale):
    pred=np.clip(raw,0,None); error=np.asarray(y)-pred
    denom=np.abs(y).sum(); smape=np.mean(2*np.abs(error)/(np.abs(y)+np.abs(pred)+1e-12))
    seasonal_wape=np.abs(np.asarray(y)-np.asarray(seasonal)).sum()/denom
    wape=np.abs(error).sum()/denom
    return {"mae":mean_absolute_error(y,pred),"median_ae":median_absolute_error(y,pred),
      "rmse":mean_squared_error(y,pred)**.5,"rmsle":mean_squared_log_error(y,pred)**.5,
      "r2":r2_score(y,pred),"wape":wape,"smape":smape,
      "mase":np.abs(error).mean()/scale,"bias":error.mean(),
      "total_absolute_error":np.abs(error).sum(),"seasonal_naive_skill":1-wape/seasonal_wape,
      "negative_prediction_count":int((np.asarray(raw)<0).sum())}
scale=train.groupby("provider_code").emergency_admissions.apply(lambda s:s.diff().abs().mean()).mean()
predictions={**baseline_predictions(validation)}
evaluation_failures={}
for name,pipeline in fitted_models.items():
    try:
        started=time.perf_counter(); raw=pipeline.predict(X_validation)
        training_log[name]["inference_milliseconds"]=1000*(time.perf_counter()-started)/len(validation)
        predictions[name]=raw
    except Exception as exc:
        evaluation_failures[name]=repr(exc)
display(evaluation_failures)
if not any(name in predictions for name in fitted_models):
    raise RuntimeError(
        "Every fitted ML model failed during validation prediction. "
        "Review evaluation_failures and rerun model definitions/training."
    )
rows=[]
for name,pred in predictions.items():
    valid=pd.Series(pred,index=validation.index).notna() & validation.emergency_admissions_lag_12.notna()
    row=metrics(y_validation[valid],np.asarray(pred)[valid],
                validation.loc[valid,"emergency_admissions_lag_12"],scale)
    rows.append({"model":name,**row,**training_log.get(name,{"training_seconds":0,"inference_milliseconds":0})})
benchmark_results=pd.DataFrame(rows).sort_values(["wape","mae","rmse", "bias"],key=lambda s:s.abs() if s.name=="bias" else s)
display(benchmark_results.drop(columns="parameters",errors="ignore"))
best_name=benchmark_results.iloc[0].model; best_raw=np.asarray(predictions[best_name]); best=np.clip(best_raw,0,None)
residual=y_validation.to_numpy()-best
validation["prediction"]=best
validation.groupby("target_month")[[TARGET,"prediction"]].sum().plot(figsize=(12,5),title="National aggregate actual vs predicted"); plt.show()
plt.scatter(y_validation,best,s=5,alpha=.3); plt.xlabel("Actual");plt.ylabel("Predicted");plt.show()
plt.plot(pd.PeriodIndex(validation.target_month,freq="M").to_timestamp(),residual,".",alpha=.3);plt.title("Residual over time");plt.show()
plt.hist(residual,bins=50);plt.title("Residual distribution");plt.show()
display(validation.assign(error=residual).groupby(pd.PeriodIndex(validation.target_month,freq="M").month).error.agg(["mean","median"]))
q80=np.quantile(residual,[.10,.90]);q95=np.quantile(residual,[.025,.975])
validation_intervals={"80":q80.tolist(),"95":q95.tolist()}
for level,q in validation_intervals.items():
    lower=np.clip(best+q[0],0,None);upper=best+q[1]
    print(level,"coverage",np.mean((y_validation>=lower)&(y_validation<=upper)))
""","manual_evaluation"),
md("## 13 — Rolling-origin tuning"),
code("""assert ALLOW_MODEL_TUNING, (
    "Tuning is disabled. Manually set ALLOW_MODEL_TUNING=True "
    "before executing this cell."
)
from sklearn.model_selection import ParameterSampler
successful_ml_results=benchmark_results[benchmark_results.model.isin(fitted_models)].copy()
if successful_ml_results.empty:
    raise RuntimeError(
        "Benchmark results contain no successfully fitted ML model. "
        "Rerun training and validation after resolving model failures."
    )
top_three=successful_ml_results.head(3).model.tolist()
search_spaces={"Random Forest":{"model__max_depth":[None,8,14],"model__min_samples_leaf":[2,4,8]},
 "Extra Trees":{"model__max_depth":[None,8,14],"model__min_samples_leaf":[2,4,8]},
 "Gradient Boosting":{"model__n_estimators":[100,200,400],"model__learning_rate":[.02,.05,.1]},
 "Histogram Gradient Boosting":{"model__max_leaf_nodes":[15,31,63],"model__learning_rate":[.02,.05,.1]},
 "XGBoost":{"model__n_estimators":[200,400,700],"model__max_depth":[3,6,9],"model__learning_rate":[.02,.05,.1]},
 "LightGBM":{"model__n_estimators":[200,400,700],"model__num_leaves":[15,31,63],"model__learning_rate":[.02,.05,.1]},
 "CatBoost":{"model__iterations":[200,400,700],"model__depth":[4,7,10],"model__learning_rate":[.02,.05,.1]},
 "Ridge Regression":{"model__alpha":[.1,1,10,100,1000]},
 "Elastic Net":{"model__alpha":[.001,.01,.1,1],"model__l1_ratio":[.1,.3,.5,.8]},
 "Linear Regression":{"model__fit_intercept":[True,False]}}
tuning_results=[]; tuned_models={}
for name in top_three:
    space=search_spaces.get(name)
    if not space: continue
    for params in ParameterSampler(space,n_iter=min(TUNING_ITERATIONS,9),random_state=RANDOM_SEED):
        fold_scores=[]
        for train_idx,valid_idx in ROLLING_FOLDS:
            candidate=clone(fitted_models[name]).set_params(**params)
            candidate.fit(train.loc[train_idx,MODEL_FEATURES],train.loc[train_idx,TARGET])
            raw=candidate.predict(train.loc[valid_idx,MODEL_FEATURES])
            fold_scores.append(np.abs(train.loc[valid_idx,TARGET]-np.clip(raw,0,None)).sum()/train.loc[valid_idx,TARGET].abs().sum())
        tuning_results.append({"model":name,"params":params,"rolling_wape":np.mean(fold_scores)})
tuning_results=pd.DataFrame(tuning_results)
if tuning_results.empty:
    raise RuntimeError(
        f"No tuning candidates were generated for top models {top_three}. "
        f"Available search spaces: {sorted(search_spaces)}"
    )
tuning_results=tuning_results.sort_values("rolling_wape")
display(tuning_results)
for name in top_three:
    candidates=tuning_results[tuning_results.model.eq(name)]
    if not candidates.empty:
        tuned=clone(fitted_models[name]).set_params(**candidates.iloc[0].params)
        tuned.fit(X_train,y_train); tuned_models[name]=tuned
""","manual_tuning"),
md("## 14 — Final test protocol, residual diagnostics, provider errors, bootstrap, and feature importance"),
code("""assert ALLOW_FINAL_EVALUATION, (
    "Final evaluation is disabled. Manually set ALLOW_FINAL_EVALUATION=True "
    "before executing this cell."
)
from sklearn.inspection import permutation_importance
successful_ml_results=benchmark_results[benchmark_results.model.isin(fitted_models)]
if successful_ml_results.empty:
    raise RuntimeError("No fitted ML candidate is available for final evaluation.")
selected_model_name=successful_ml_results.iloc[0].model
final_model=tuned_models.get(selected_model_name,fitted_models.get(selected_model_name))
if final_model is None: raise RuntimeError("Selected candidate is not a trained ML pipeline.")
raw_test=final_model.predict(test[MODEL_FEATURES]); clipped_test=np.clip(raw_test,0,None)
valid=test.emergency_admissions_lag_12.notna()
test_metrics=metrics(test.loc[valid,TARGET],raw_test[valid],test.loc[valid,"emergency_admissions_lag_12"],scale)
test_errors=test.loc[valid,["provider_code","provider_name","target_month",TARGET]].copy()
test_errors["prediction"]=clipped_test[valid];test_errors["error"]=test_errors[TARGET]-test_errors.prediction
provider_error_metrics=test_errors.groupby(["provider_code","provider_name"]).agg(
 rows=("error","size"),mae=("error",lambda x:x.abs().mean()),bias=("error","mean")).reset_index()
display(test_metrics);display(provider_error_metrics.nlargest(10,"mae"));display(provider_error_metrics.nsmallest(10,"mae"))
display(test_errors.groupby("target_month").error.agg(["mean","median"]))
test_errors["volume_quartile"]=pd.qcut(test_errors[TARGET],4,duplicates="drop")
display(test_errors.groupby("volume_quartile",observed=True).error.agg(["mean","median"]))
for level,q in validation_intervals.items():
    lower=np.clip(clipped_test+q[0],0,None);upper=clipped_test+q[1]
    test_metrics[f"interval_{level}_coverage"]=np.mean((test[TARGET]>=lower)&(test[TARGET]<=upper))
rng=np.random.default_rng(BOOTSTRAP_SEED);providers=test_errors.provider_code.unique();boot=[]
for _ in range(1000):
    sampled=rng.choice(providers,len(providers),replace=True)
    blocks=pd.concat([test_errors[test_errors.provider_code.eq(code)] for code in sampled])
    boot.append(metrics(blocks[TARGET],blocks.prediction,
      np.maximum(blocks[TARGET]-blocks.error,0),scale))
bootstrap_ci={key:np.quantile([row[key] for row in boot],[.025,.975]).tolist()
              for key in ["mae","rmse","wape","smape"]}
display(bootstrap_ci)
sample=validation.sample(min(3000,len(validation)),random_state=RANDOM_SEED)
importance=permutation_importance(final_model,sample[MODEL_FEATURES],sample[TARGET],
 scoring="neg_mean_absolute_error",n_repeats=8,random_state=RANDOM_SEED,n_jobs=N_JOBS)
feature_importance=pd.DataFrame({"feature":MODEL_FEATURES,
 "importance_mean":importance.importances_mean,"importance_std":importance.importances_std}).sort_values("importance_mean",ascending=False)
display(feature_importance)
""","manual_evaluation"),
md("## 15 — Final model-selection report\n\nPrimary metric is validation WAPE. Tie-breakers are MAE, RMSE, absolute bias, seasonal-naive skill, provider stability, latency, then simplicity. A complex model should not deploy unless it reliably beats seasonal naive."),
code("""assert ALLOW_FINAL_EVALUATION, (
    "Final evaluation is disabled. Manually set ALLOW_FINAL_EVALUATION=True "
    "before executing this cell."
)
selection=benchmark_results.rename(columns={"wape":"validation_wape","mae":"validation_mae",
 "rmse":"validation_rmse","smape":"validation_smape","mase":"validation_mase",
 "bias":"validation_bias"})[["model","validation_wape","validation_mae","validation_rmse",
 "validation_smape","validation_mase","validation_bias","seasonal_naive_skill",
 "training_seconds","inference_milliseconds","negative_prediction_count"]].copy()
deployable=selection[selection.model.isin(fitted_models)].copy()
eligible=deployable[deployable.seasonal_naive_skill>0]
if eligible.empty:
    raise RuntimeError(
        "No fitted ML model reliably beats seasonal naive on validation WAPE. "
        "Do not export a complex model; review features and validation design."
    )
recommended=eligible.sort_values(["validation_wape","validation_mae","validation_rmse"]).iloc[0].model
MODEL_OVERRIDE=None;MODEL_OVERRIDE_REASON=""
if MODEL_OVERRIDE:
    if MODEL_OVERRIDE not in fitted_models:
        raise ValueError("MODEL_OVERRIDE must name a successfully fitted ML pipeline.")
    if MODEL_OVERRIDE_REASON.strip()=="":raise ValueError("Document MODEL_OVERRIDE_REASON.")
    recommended=MODEL_OVERRIDE
selection["selected"]=selection.model.eq(recommended)
selection["selection_reason"]=np.where(selection.selected,
 MODEL_OVERRIDE_REASON or "Best validation WAPE under baseline-skill and tie-break policy","Not selected")
selected_model_name=recommended
display(selection)
""","manual_evaluation"),
md("## 16 — Artifact export and model card"),
code(f"""assert ALLOW_MODEL_EXPORT, (
    "Model export is disabled. Manually set ALLOW_MODEL_EXPORT=True "
    "before executing this cell."
)
import joblib
required=["final_model","test_metrics","benchmark_results","provider_error_metrics","feature_importance"]
missing=[name for name in required if name not in globals()]
if missing:raise RuntimeError(f"Run required manual stages first: {{missing}}")
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
joblib.dump(final_model,ARTIFACT_DIR/"healthflow_emergency_admissions_pipeline.joblib")
feature_schema={{"features":MODEL_FEATURES,"numerical":NUMERICAL,"categorical":CATEGORICAL,
 "target":TARGET,"optional_targets":OPTIONAL_TARGETS}}
metadata={{"project":"HealthFlow","model_name":"Emergency Admissions Forecasting Model",
 "task_type":"provider_level_time_series_regression",
 "data_source":"NHS England Monthly A&E Attendances and Emergency Admissions",
 "forecast_target":"next-month emergency admissions","forecast_horizon_months":1,
 "data_start_month":str(features.reporting_month.min()),"data_end_month":str(features.reporting_month.max()),
 "selected_model":selected_model_name,"random_seed":RANDOM_SEED,
 "training_timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "feature_names":MODEL_FEATURES,"validation_metrics":benchmark_results.query("model==@selected_model_name").iloc[0].to_dict(),
 "test_metrics":test_metrics,"forecast_intervals":{{"80_percent":True,"95_percent":True}},
 "intended_use":"Hospital operations and capacity-planning research",
 "patient_level_use":False,"clinical_use_prohibited":True}}
configuration={{"horizon_months":1,"optional_horizons":[2,3],
 "training_target_end":TRAIN_TARGET_END,"validation_target_period":[VALIDATION_TARGET_START,VALIDATION_TARGET_END],
 "test_target_start":TEST_TARGET_START,"interval_method":"empirical validation residual quantiles",
 "covid_sensitivity_exclusion":EXCLUDE_COVID_SENSITIVITY}}
for name,payload in {{"feature_schema.json":feature_schema,"model_metadata.json":metadata,
 "forecast_configuration.json":configuration,"validation_metrics.json":metadata["validation_metrics"],
 "test_metrics.json":test_metrics}}.items():
    (ARTIFACT_DIR/name).write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
benchmark_results.to_csv(ARTIFACT_DIR/"benchmark_results.csv",index=False)
provider_error_metrics.to_csv(ARTIFACT_DIR/"provider_error_metrics.csv",index=False)
feature_importance.to_csv(ARTIFACT_DIR/"feature_importance.csv",index=False)
model_card=f'''# HealthFlow Emergency Admissions Forecasting Model

> {DISCLAIMER}

## Purpose, target, and horizon
Provider-level operational forecasting of next-month total emergency admissions; optional direct horizons are two and three months.
## Dataset and date range
Official NHS England Monthly A&E Attendances and Emergency Admissions, {{metadata["data_start_month"]}}–{{metadata["data_end_month"]}}.
## Provider eligibility and continuity
At least {{MINIMUM_HISTORY_MONTHS}} months and no more than {{MAXIMUM_MISSING_MONTH_FRACTION:.0%}} missing months. Codes are never merged by name similarity.
## Schema and aggregation
Explicit audited aliases normalise historical schemas. Provider rows exclude national/system totals. Official all-type totals are preferred; otherwise mutually exclusive types are summed.
## Features and leakage prevention
Calendar, shifted lags, shifted rolling summaries, rates, trends, historical-only provider statistics, provider code, and a COVID-disruption flag. Provider name is display-only.
## Splitting and rolling-origin validation
Chronological target-month splits and expanding-window rolling-origin folds; no shuffled validation.
## Models and baselines
{{list(models)}} plus last-value, seasonal-naive, and moving-average baselines.
## Selected model and results
Selected: {{selected_model_name}}. Validation: {{json.dumps(metadata["validation_metrics"],default=str)}}. Test: {{json.dumps(test_metrics,default=str)}}.
## Forecast intervals
Transparent empirical validation-residual 80% and 95% intervals; these are not full probabilistic certainty.
## Limitations
Pandemic disruption is a structural break. Provider mergers, closures, code/footprint changes, reporting revisions, missingness, and measurement changes can degrade forecasts. Provider error varies and requires monitoring.
## Intended and prohibited uses
Hospital operations research only; no patient-level, clinical, diagnostic, triage, treatment, or autonomous decisions.
## Retraining
Refresh official data, rerun schema/continuity checks, rebuild leakage-safe features, retune with rolling origins, keep final test isolated, and revalidate intervals and provider errors.
'''
(ARTIFACT_DIR/"model_card.md").write_text(model_card,encoding="utf-8")
""","manual_export"),
md(f"""## 17 — Limitations and responsible use

Monthly reporting may be revised and schemas evolve. COVID-19 is an exceptional structural break. Provider mergers, closures, renaming, code changes, and reporting-footprint changes can interrupt series; no name-similarity merging is performed. Missing reports are not true zeros. Empirical intervals are uncertainty summaries, not guarantees. Performance must be monitored nationally and by provider.

> **{DISCLAIMER}**"""),
]
from notebook_diagnostics import diagnostic_cells
cells[-1:-1] = diagnostic_cells()

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}
OUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(OUT)
