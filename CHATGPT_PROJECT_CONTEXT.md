# HEALTHFLOW — Complete ChatGPT Project Context

Updated: 9 November 2026. Repository: `F:\projhosp`. Platform: Windows, PowerShell.

Use this document as the working context for future discussions and development. It describes the implementation inspected in the repository, not a proposed design. Source code and exported artifacts take precedence if they subsequently change. Verification results below are historical results from the recent implementation; they are not a claim that every check was rerun when this document was written.

## 1. Project identity and purpose

Full title: **HEALTHFLOW: A Predictive Digital Twin for Emergency Admissions Forecasting and Hospital Resource Optimisation**.

HealthFlow is a hospital staff portal that connects monthly emergency-admissions forecasting to recorded hospital capacity, scenario simulation, and human-reviewed capacity recommendations. Its digital-twin scope is a staff-maintained operational representation plus aggregate scenario modelling. It is not a real-time replica of a hospital or a patient-level clinical model.

The intended users are hospital staff: administrators, operational planners, bed managers, and authorised viewers. Earlier references to a public interface mean a usable staff portal, not a publicly accessible patient service. Do not redesign it as a patient-facing application.

The operational workflow is:

1. Authenticate and select a hospital workspace.
2. Maintain wards, beds, emergency queue counts, staffing, equipment, and tasks.
3. Enter or import completed monthly activity.
4. Generate and save a next-month emergency-admissions forecast.
5. Combine the forecast with recorded capacity and explicit planning assumptions.
6. Run a monthly flow simulation and constrained capacity optimisation.
7. Review the recommendation; an administrator can approve or reject it.
8. Track operational follow-up tasks. Approval does not execute staffing or bed allocation.

## 2. User preferences and UI decisions

- The main interface must use operational language understandable to hospital staff.
- WAPE, R², benchmark rankings, and detailed model performance should not dominate staff workflows. Dedicated model diagnostics are under Administration and require an administrator on the server.
- Show hospital identity, reporting month, admission estimates, bed availability, staffing gaps, emergency flow, and actionable next steps.
- Do not describe staff-entered records as live telemetry.
- The user explicitly requested removal of the top **DEMONSTRATION WORKSPACE** banner. It has been removed. Sample data remain synthetic, and their underlying provenance has not changed.
- Preserve the teal staff-portal design, readable cards and tables, clear status indicators, persistent navigation, and mobile navigation.
- Sidebar cropping in long screenshots was fixed using a viewport-height app shell and independently scrolling workspace. The page header remains sticky. Navigation resets workspace scrolling when the route changes.
- Screenshots must show the complete intended navigation and readable input/output content. Capture actual running application states, not invented interface images.
- Prefer completing authorised work and verifying it rather than repeatedly asking permission for routine reversible implementation details.

## 3. Architecture and stack

### Frontend

Location: `frontend/healthflow`.

React 19, TypeScript, Vite 8, React Router, Axios, Lucide icons, and CSS form the staff interface. Additional installed libraries include Recharts, Zustand, React Hook Form, Zod, and Tailwind tooling; installation does not mean every library is used by every page.

Important files:

- `src/App.tsx`: login, routing, staff shell, navigation, role-aware UI, scroll reset.
- `src/workspace.tsx`: selected hospital context, operational board retrieval, refresh, permissions.
- `src/staff.tsx`: overview, beds/wards, emergency flow, resources, planning and actions.
- `src/shift-equipment.tsx`: shift and equipment entry.
- `src/pages.tsx`: monthly forecast form/CSV import, results, model diagnostics, assistant and policy interfaces.
- `src/api.ts`: Axios client, bearer token handling and expired-session events.
- `src/index.css`: application styling and responsive shell.
- `vite.config.js`: Vite configuration. This repository does not use `vite.config.ts`.

Default API base: `http://localhost:8000/api/v1`, overridable with `VITE_API_URL`. Development frontend: `http://localhost:5173`.

### Backend

Location: `backend`.

FastAPI, Pydantic, SQLAlchemy, Uvicorn, scikit-learn/joblib, pandas/NumPy, SimPy, OR-Tools, and a hosted Groq assistant with local semantic retrieval. SQLAlchemy uses SQLite by default for local development; Docker Compose uses PostgreSQL.

Important files/directories:

- `app/main.py`: app startup, service initialisation, routers, health endpoints, metrics.
- `app/core/config.py`: environment configuration.
- `app/api/router.py`: authentication, forecasts, diagnostics, legacy capacity/simulation/optimisation routes, approvals, intelligence and policies.
- `app/api/operations.py`: hospital-specific operational state and forecast-linked planning.
- `app/db/models.py`: persistence models.
- `app/ai/forecasting/`: model loader, feature builder, forecast service.
- `app/services/simulation.py`: flow simulation.
- `app/services/optimisation.py`: constrained recommendations.
- `app/services/intelligence.py`: Groq agent with local semantic/keyword retrieval.
- `app/cli/import_nhs_forecast_data.py`: processed-data importer.
- `tests/`: backend verification, including `test_staff_operations.py`.

Default API: `http://localhost:8000`. Interactive API documentation: `/docs`. API prefix: `/api/v1`.

The application creates missing tables at startup with `Base.metadata.create_all`. This is the current development behaviour, not a complete production migration strategy.

## 4. Authentication and permissions

Existing roles: `admin`, `planner`, `viewer`.

- Administrators and planners can maintain operational records and generate forecasts/scenarios.
- Viewers can inspect operational data but cannot generate forecasts/simulations or maintain operational records through protected write routes.
- Administrators alone can access protected model metric/benchmark endpoints and approve/reject recommendations.
- The development demonstration-workspace endpoint is administrator-only and unavailable in production mode.
- Login inputs are blank rather than prefilled with administrator credentials.
- Authentication uses JWT bearer tokens. The current frontend keeps its token in localStorage and clears it after an expired/invalid authenticated session.
- Accounts currently share an installation. Hospital identifiers are checked for related records, but this does not constitute per-hospital account entitlements or full tenant isolation.
- Hospital SSO, MFA, self-service account provisioning, and per-hospital access grants are not implemented.

Development seed credentials, if the existing database/configuration has not changed them:

`admin@healthflow.local` / `ChangeMe123!`

These are documented development defaults, not credentials for deployment. Changing seed settings does not reset an already-created database user's password.

## 5. Frontend modules and their behaviour

### Hospital overview

Shows the selected hospital's stored operational state and links into staff workflows. Hospital selection is persisted locally and the board can be refreshed from the API. New hospital workspaces start empty. The optional development sample is City General Hospital (`DEMO-HOSP-01`).

### Beds & wards

Staff can create wards with a floor label, specialty, bed count and capability context. Layout is a schematic grouping, not an architectural floor-plan import. New beds start blocked and unstaffed until confirmed.

Bed states: `available`, `occupied`, `reserved`, `cleaning`, `blocked`. Each bed has staffing state, an operational note, and a version for concurrent-edit protection. An available bed must be staffed. Stale updates return a conflict instead of silently overwriting another edit.

Immediate availability differs from monthly operational capacity. Monthly capacity counts staffed, non-blocked beds, including occupied/reserved/cleaning beds; it is not simply the count immediately free.

### Emergency flow

Stores aggregate counts awaiting assessment and awaiting a bed, plus high/medium/low priority counts already assessed and recorded by staff. These are operational snapshots, not individual patient records. The software does not determine clinical priority or predict triage categories.

### Demand forecast

Uses the selected hospital identity. Staff enter monthly rows or import a plain CSV. Required fields:

```csv
month,total_ae_attendances,emergency_admissions,attendances_under_4_hours,decision_to_admit_waits_over_4_hours
2025-07,11240,4180,8260,620
```

The single example row illustrates format only; a forecast requires 13–120 consecutive completed monthly rows. Dates use `YYYY-MM`. Inputs are nonnegative integer counts, with positive A&E attendances and server-side consistency validation. Current/future months are rejected; missing months cannot be silently treated as zero. CSV upload limit is 1 MB; use plain numbers without thousands separators or quoted comma-containing fields.

The forecast targets the month immediately after the last input month. Historical input therefore produces a retrospective forecast, not automatically a forecast for the calendar month following today's date. The UI displays the predicted admission count, target month and input-history period, and saves the forecast for planning.

### Staffing & equipment

Monthly resource records include month, available staff hours, equipment-availability context and notes. The staffing record matching the forecast target month supplies the capacity plan's staffing budget.

Shift records include date, Day/Evening/Night, team, required/available staff and hours per person. Reusing the date/shift/team key updates the record; changing that key creates another record. Displayed staffing gaps are arithmetic comparisons, not staffing forecasts. Partial shift records do not automatically replace the monthly budget.

Equipment records include type/name, location, total and available units. Available units cannot exceed total. Equipment stock is saved context; the optimiser does not yet enforce equipment-dependent bed constraints.

### Capacity planning

The server links a saved hospital forecast to current staffed/non-blocked beds and matching-month staffing hours. Inputs include average stay, target occupancy, staff-hours per admission, and upper bounds on additional beds/staff-hours.

With forecast admissions A, mean stay L hours, target occupancy O, staffed beds B, and D days in the target month:

- Required bed-hours = A × L / O.
- Available bed-hours = B × D × 24.
- Each extra bed contributes D × 24 hours.
- Required staff-hours = A × staff-hours per admission.
- Extra-bed cost = £500 × D per extra bed.
- Additional staff cost = £45 per extra staff-hour.

The costs are illustrative scenario assumptions. OR-Tools selects integer additions within the configured limits. Feasible results await approval; impossible limits produce an infeasible result.

### Action queue

Displays plan decisions and operational tasks. Only feasible pending plans can be reviewed. Approval/rejection is persisted and audited, but does not modify actual staffing or allocate beds. Tasks have title, owner, routine/urgent priority, note and status (`open`, `in_progress`, `done`). Task priority is distinct from patient clinical priority.

### Operations assistant and Policy library

The assistant now uses Groq (`openai/gpt-oss-120b`) with local BGE-small embeddings and persistent SQL passage vectors. It performs semantic cosine retrieval combined with keyword overlap. PDF/TXT/Markdown upload and pasted text are supported, with passage IDs, excerpts and PDF page citations. A HealthFlow software reference is indexed and explicitly labelled non-clinical. Policies remain installation-wide.

Tools read the selected hospital's recorded beds, wards, emergency counts, forecasts, resources, shifts, equipment, tasks and plans. Admin/planner users can enable computation previews per message and explicitly ask to run the trained forecast model or existing capacity simulator/optimiser. Computations are unsaved previews; no allocation, bed editing or plan approval tool exists. The model cannot change hospital scope or issue arbitrary SQL.

Forecast submissions now preserve validated monthly inputs in an additive history table. Legacy predictions do not contain those inputs: submit monthly history again before rerunning them through the assistant. The assistant never invents input history. Current-date and historical-target flags distinguish retrospective forecasts from future targets.

Conversations are bound to user and hospital and persisted; the last six messages provide context. There are four completion rounds and six executed tool calls at most. Provider failures and quota limits are reported explicitly. Tool results are shown independently of generated prose. Retrieved excerpts and selected summaries leave the machine for Groq even though embeddings are local. No Ollama service is required for this assistant.

The key is held in untracked `backend/.env.local`, never frontend code or this document. See `docs/RAG_ASSISTANT.md` for limits, configuration, test evidence and implementation details; this supersedes older keyword-only/Ollama assistant descriptions.

### Administration

Contains technical model diagnostics such as validation/test metrics and benchmarks. Keeping these outside normal staff screens is a deliberate UX choice. Some model metadata still exists in forecast API responses; hiding technical UI fields is not equivalent to removing them from all payloads.

## 6. Forecasting model and data

Source: official NHS England Monthly A&E Attendances and Emergency Admissions.

Task: provider-level time-series regression for next-month aggregate emergency admissions. Deployed model: exported Random Forest pipeline with 47 input features. The app loads the saved artifact and builds matching features; normal startup and forecasting do not train a model.

Artifact directory: `backend/model_artifacts/emergency_admissions_forecast`.

Core artifact: `healthflow_emergency_admissions_pipeline.joblib`.

Supporting files include `feature_schema.json`, `model_metadata.json`, `forecast_configuration.json`, `validation_metrics.json`, `test_metrics.json`, `benchmark_results.csv`, `provider_error_metrics.csv`, `feature_importance.csv`, and `model_card.md`.

Processed data directory: `backend/dataset/processed/nhs_england_ae`, including `provider_month_panel.parquet` and `forecasting_features.parquet`.

Exported metadata records data from April 2018 to June 2026. Chronological target-month splits are training through December 2023, validation January–December 2024, and test from January 2025. The recently reproduced test diagnostics cover January 2025–June 2026, 3,231 eligible provider-month rows and 183 providers.

Features include provider code, calendar/seasonality, attendance/wait counts, lagged admissions/attendances, shifted rolling statistics, growth/change rates, historical provider summaries and a COVID-disruption indicator. Target columns are excluded from predictors. Training uses chronological/rolling-origin evaluation rather than random time-series splitting.

Saved scores:

- Validation WAPE: approximately 4.749%.
- Test WAPE: approximately 5.317%.
- Test MAE: approximately 155.30 admissions per evaluated provider-month.
- Test RMSE: approximately 347.92 admissions.
- Test R²: approximately 0.98564.

These are retrospective dataset metrics, not a guarantee of accuracy for a newly onboarded hospital. WAPE is sum of absolute errors divided by sum of actual admissions; it must not be relabelled as a generic accuracy percentage.

The service rounds the prediction to a nonnegative integer for display and preserves the raw result. Forecast response interval bounds are currently null. Notebook interval coverage evaluation exists, but this does not mean usable calibrated per-request intervals are deployed. Global permutation importance is not causal attribution or an explanation specific to one patient's case.

Only next-month admissions are served. Prepared optional h2/h3 target columns do not establish deployed two-/three-month forecasting. No hourly demand, ward-level demand, length-of-stay prediction, discharge prediction, or patient-level clinical model has been implemented.

## 7. Simulation scope

SimPy models aggregate forecast-cohort flow over the target month. The monthly planning path uses the actual calendar length, twenty deterministic seeded replications, and an initially empty system. Occupancy is time-weighted.

Wait statistics describe admissions that obtained a bed during the simulation. The end-of-month waiting queue is reported separately. Do not present the wait percentile as covering every still-waiting admission.

The current simulation does not include existing inpatients at time zero, elective activity, individual patient attributes, clinical routing, ward-specific transfers or equipment/skill constraints. Its results are scenario estimates conditioned on supplied assumptions, not real-world observed waiting times.

## 8. ML notebook additions

Main notebook: `backend/notebooks/healthflow_main_model_training.ipynb`.

Existing stages include configuration, environment and manifest audit, schema mapping, provider panel/continuity checks, exploratory analysis, leakage-safe feature review, chronological splits, baselines, benchmarking, rolling-origin tuning, final test evaluation, model selection, export, and limitations.

An additional diagnostics section was inserted before limitations. It contains sixteen new markdown/code cells, including eight executed code cells and seven embedded figure outputs:

1. Training-feature Pearson correlation matrix.
2. Actual-versus-predicted scatter, residual-versus-prediction scatter and residual histogram.
3. Monthly actual/predicted totals with monthly WAPE trend.
4. Provider-by-month signed error matrix for the 15 highest-volume evaluated providers.
5. Validation benchmark ranking and MAE/RMSE/WAPE comparison matrix.
6. Top 15 permutation importances with repeat-standard-deviation error bars.
7. MAE and WAPE by observed admission-volume quartile, plus a summary table.

Interpretation details: residual = actual minus prediction, so positive residual means underprediction. Grey error-matrix cells mean missing observations. Benchmark matrix colours are normalised within each metric, while numbers retain original units. Importance is increase in validation MAE after shuffling, not a percentage. Volume quartiles are retrospective descriptive groups, not clinical risk classes. Monthly plotted totals cover evaluated providers, not necessarily all NHS activity. A classification confusion matrix is not appropriate for the raw regression target.

The new section loads the saved model, runs inference, and checks MAE/WAPE against exported test metrics. It does not train or overwrite the model. New cells executed successfully and the model checksum was unchanged. Existing notebook outputs were preserved.

Reusable definitions: `backend/scripts/notebook_diagnostics.py`. Generator: `backend/scripts/build_main_model_notebook.py`, updated to include these cells. Do not run the generator casually: it rewrites the notebook with an unexecuted template.

PNG exports: `backend/reports/emergency_admissions_forecast/figures/extended_diagnostics`.

Notebook backup: `artifacts/notebook-diagnostics/healthflow_main_model_training.before.ipynb`.

The existing `validate_main_model_notebook.py` is an **untrained-template safety audit** that rejects trained artifacts and enabled manual stages. It is not a general validity test for the now-trained notebook. The current notebook contains enabled training/evaluation/export flags; avoid Run All if the intention is only to inspect graphs. Run the additional diagnostics section independently.

## 9. Persistence and API map

Operational models: Hospital, Ward, Bed, EmergencySnapshot, ResourceRecord, OperationalTask, StaffShift and EquipmentStock. New assistant tables: PolicyChunk, AgentConversationScope and HospitalForecastHistory. Existing entities include users, forecasts, simulations, optimisation plans, audit events, policies and conversations. Operational mutations are audited. Bed edits have optimistic concurrency checks; this does not mean every table has identical version protection.

Principal routes, relative to `/api/v1`:

| Route | Purpose |
|---|---|
| POST `/auth/login`; GET `/auth/me` | Authentication and current user |
| POST `/forecasts/hospital`; GET `/forecasts/history` | Forecast creation/history |
| GET `/model/status`, `/model/metrics`, `/model/benchmarks` | Model status and protected diagnostics |
| GET/POST `/operations/hospitals` | Hospital workspaces |
| POST `/operations/demo` | Development sample records |
| GET `/operations/{hospital_id}/board` | Combined operational board |
| POST `/operations/{hospital_id}/wards` | Ward and bed creation |
| PATCH `/operations/{hospital_id}/beds/{bed_id}` | Versioned bed update |
| POST `/operations/{hospital_id}/emergency` | Aggregate emergency snapshot |
| PUT `/operations/{hospital_id}/resources` | Monthly resource record |
| PUT `/operations/{hospital_id}/shifts` | Shift upsert |
| PUT `/operations/{hospital_id}/equipment` | Equipment upsert |
| POST/PATCH `/operations/{hospital_id}/tasks[/{task_id}]` | Task creation/status |
| POST `/operations/{hospital_id}/planning` | Forecast-linked monthly plan |
| POST `/optimisations/{plan_id}/approval` | Administrator decision |
| GET/POST `/simulations`, `/optimisations`, `/capacity` | Existing generic APIs |
| GET `/operations-intelligence/status`; POST `/operations-intelligence` | Local assistant |
| GET/POST `/policies` | Policy records |

Health endpoints are outside the prefix: `/health/live`, `/health/ready`; Prometheus endpoint: `/metrics`. A live API can still have degraded model readiness (HTTP 503). A healthy process alone does not establish a working forecast pipeline.

## 10. Verification and screenshot evidence

Recent implementation checks: twenty-four backend tests passed; TypeScript check and production frontend build passed; ten browser verification groups passed. Browser checks covered real authentication, persisted bed changes across reload, emergency/resource/shift/equipment entry, CSV import, actual model inference, linked planning, actions, admin benchmarks and mobile navigation. These checks are evidence for the tested flows, not exhaustive production certification.

Sample input: `sample_data/hospital_prediction_test.csv`, July 2025–July 2026. Verified output: **4,411 admissions for August 2026**. This remains a historical sample scenario; do not silently relabel it as a current November forecast.

Example planning state: 120 beds, of which 116 are staffed/non-blocked; monthly staff budget 15,000 hours; 20-hour assumed stay; 85% target occupancy; four staff-hours per admission. Result: 24 additional beds, 2,644 additional staff-hours, illustrative monthly cost £490,980. The plan is advisory/pending review. It compares current recorded inventory with a historical sample month.

Evidence directory: `artifacts/staff-portal-implementation`.

- `verify-ui.cjs`: original browser verification.
- `refresh-screenshots.cjs`: updated screenshot capture and layout checks.
- `updated-screenshots/`: ten fresh screenshots after banner/sidebar fixes.
- `HealthFlow-Updated-Screenshots.zip`: screenshot package.
- `before/`: pre-change database/frontend backup.

Updated screenshot names: `01-staff-login.png`, `02-hospital-overview.png`, `03-bed-inventory.png`, `04-emergency-flow.png`, `05-staffing-resources.png`, `06-forecast-input.png`, `07-forecast-result.png`, `08-connected-capacity-plan.png`, `09-action-queue.png`, `10-mobile-emergency.png`.

## 11. Running locally on this Windows workspace

Use two PowerShell terminals. The existing virtual environment is at `F:\projhosp\.venv`. Calling its Python executable directly avoids activation-policy issues. Starting from the backend directory matters because database/model/data defaults are relative paths.

### Terminal 1 — backend

```powershell
Set-Location F:\projhosp\backend
& F:\projhosp\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Terminal 2 — frontend

```powershell
Set-Location F:\projhosp\frontend\healthflow
npm run dev
```

Open `http://localhost:5173`. API documentation: `http://localhost:8000/docs`.

Use Ctrl+C in each terminal to stop that development server. If a port is occupied, check whether the project is already running before starting another instance. `--strictPort` prevents Vite from silently changing to a port excluded by CORS.

### Install dependencies only if missing or setting up another checkout

The current environment already exists; do not recreate it unnecessarily.

```powershell
Set-Location F:\projhosp
# Only if .venv does not exist; the current workspace uses Python 3.13:
py -3.13 -m venv .venv

& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt

Set-Location F:\projhosp\frontend\healthflow
npm ci
```

`requirements-dev.txt` already includes runtime requirements. `npm ci` uses the lockfile; use `npm install` if deliberately updating dependencies or working without the lockfile. These setup commands install the repository's pinned versions and were documented, not reinstalled during context preparation.

### Configuration

Backend settings read `.env` then `.env.local` relative to the backend working directory; local overrides win. Defaults support localhost development without creating a file. Tracked `backend/.env` contains safe defaults; put secrets and local overrides in `backend/.env.local`:

```dotenv
APP_ENV=development
DATABASE_URL=sqlite:///./healthflow.db
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
FORECAST_MODEL_DIR=model_artifacts/emergency_admissions_forecast
FORECAST_DATA_DIR=dataset/processed/nhs_england_ae
GROQ_API_KEY=your_backend_only_key
GROQ_MODEL=openai/gpt-oss-120b
```

Do not overwrite an existing `.env`. The root `.env.example` is primarily for Compose and has a different frontend origin. Frontend optional `.env.local`:

```dotenv
VITE_API_URL=http://localhost:8000/api/v1
```

Restart the affected server after changing its environment configuration. Use localhost consistently in browser URLs to match configured CORS origins.

### Health checks and verification

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready

Set-Location F:\projhosp
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

Set-Location F:\projhosp\frontend\healthflow
npx --no-install tsc --noEmit
npm run build
```

If readiness is degraded, check startup logs, the saved pipeline and metadata files, dependency compatibility and the backend working directory. A missing artifact is not fixed by inventing predictions or silently retraining.

### Notebook

```powershell
Set-Location F:\projhosp
# Only if notebook/ML dependencies are missing:
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements-ml.txt

& .\.venv\Scripts\python.exe -m jupyter notebook backend\notebooks\healthflow_main_model_training.ipynb
```

The new plots are embedded already. Run only the additional diagnostics section to refresh them without retraining/exporting.

### Groq assistant

The backend uses `GROQ_API_KEY` and `GROQ_MODEL` from `backend/.env.local`. The key is already configured locally; rotate the chat-exposed key and replace its value there. Restart the backend after changing it. The local embedding model is already downloaded into `backend/.rag_cache`. On another machine, install updated backend requirements and allow its first-use model download. Ollama is no longer required. Upload references through Policy library, then use Operations assistant. See `docs/RAG_ASSISTANT.md`.

### Docker alternative

The repository has `docker-compose.yml` and a root `.env.example`. Prepare a root `.env` from the example only if one does not already exist, configure its values, then:

```powershell
Set-Location F:\projhosp
docker compose up --build
```

Compose serves the frontend on `http://localhost:3000` and API on port 8000, using PostgreSQL. This is a separate database from the local SQLite setup; local sample records do not automatically appear there. Do not run another backend on port 8000 simultaneously. Docker was not revalidated during this documentation update.

## 12. Boundaries and next work

The latest assistant implementation and verification are documented in `docs/RAG_ASSISTANT.md`; the original screenshot package predates this upgrade. New evidence lives under `artifacts/rag-agent`.

Implemented features must be distinguished from suggestions. Potential future work includes approved hospital data feeds, per-hospital entitlements, richer floor plans, ward-specific forecasts, discharge/length-of-stay models, calibrated forecast intervals, shift/skill/equipment-aware optimisation and data freshness/drift monitoring. Each needs its own data contract, implementation and validation; none should be described as already delivered.

Current operational facts:

- No live EHR, ADT, roster or sensor integration is connected.
- No patient-identifiable operational workflow or clinical priority prediction is implemented.
- No automatic resource allocation is executed by the application.
- Current sample records remain synthetic despite removal of the prominent demo banner.
- A successful build or screenshot does not establish deployment readiness.

Related documents: `README.md`, `docs/STAFF_PORTAL.md`, `backend/MODEL_TRAINING_README.md`, `docs/HOSPITAL_DEPLOYMENT.md`. The deployment document records additional organisational and technical work; this context does not assert that those gates are complete.

For future changes, preserve the trained artifact unless explicitly doing a model-development task; avoid mixing training and inference; keep technical diagnostics separate from normal staff navigation; preserve units/calendar-month consistency; test persistence and permissions, not just appearance; document assumptions and unimplemented features honestly; and update this context when behaviour changes.

Repository packaging: `.env` files contain safe defaults/placeholders. Keep live credentials in ignored `.env.local`; backend settings load it after `.env`. The trained `.joblib` is tracked with Git LFS.
