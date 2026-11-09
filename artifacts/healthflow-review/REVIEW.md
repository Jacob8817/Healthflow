# HEALTHFLOW functional review

Reviewed 8 November 2026. Project: **A Predictive Digital Twin for Emergency Admissions Forecasting and Hospital Resource Optimisation**.

**Verdict: the core hospital forecasting flow works end to end. The project is a functioning prototype with confirmed UI/backend defects and incomplete integration; it is not yet a fully completed operational system.**

## Verified behaviour

| Area | Result |
| --- | --- |
| Frontend production build | `npm run build` passed. |
| TypeScript | `npx --no-install tsc --noEmit` passed. |
| Existing backend tests | 5 passed when run from `backend`. |
| Browser/API checks | 21 recorded checks completed; no uncaught browser errors or HTTP 5xx responses in the tested normal flows. |
| Authentication | Login, authenticated API access, rejection of unauthenticated requests, and logout worked. |
| Model readiness | `/health/ready` returned HTTP 200; Random Forest artifact `c8d08873d644` loaded. |
| Forecast | Imported the existing 13-row CSV in the frontend, clicked Generate hospital prediction, verified the displayed number equals the real API result, and retrieved the saved forecast from history. |
| Input validation | Missing hospital name and blank monthly fields blocked in the UI. API rejected fewer than 13 months, duplicate months, negative admissions, and within-four-hour counts exceeding total attendance with HTTP 422. |
| Simulation | Button ran 20 replications: 96.7% reported mean occupancy, 117.0-hour reported p95 wait, high capacity risk. These are the fixed baseline scenario results. |
| Optimisation | Button returned 14 extra beds and 300 extra staff hours, estimated incremental cost £20,500, pending human approval. This is the fixed demonstration constraint set. |
| Capacity and policies | Pages load successfully; database lists were empty. |
| Operations Intelligence | Endpoint/UI returned a clear degraded response because the configured Ollama service was unavailable. Successful language-model generation was not verified. |
| Mobile smoke check | At 390px width, overview had no horizontal document overflow and the menu opened the forecasting page. This is not an exhaustive responsive/accessibility audit. |

`npm run lint` exited successfully, but the ESLint configuration only includes `.js/.jsx`; it does not lint the main `.tsx` application. The README's root-level `pytest backend/tests` command fails to import `app` in this environment. Working command: from `backend`, run `..\.venv\Scripts\python.exe -m pytest tests -q`. The passing run emitted dependency deprecation and pytest cache-permission warnings.

## Demonstrated forecast

- Test hospital: **City General Hospital (Test Data)**; identifier `DEMO-HOSP-01`.
- Input: `sample_data/hospital_prediction_test.csv`, July 2025 through July 2026, 13 consecutive months.
- Latest input month: 11,590 A&E attendances; 4,345 emergency admissions; 8,190 attendances within four hours; 675 decision-to-admit waits over four hours.
- Target: **August 2026**, the month after the supplied history, not the month after this review date.
- Raw model output: **4410.560852603583**; displayed rounded prediction: **4,411 admissions**.
- Exported model validation WAPE: 4.749%; test WAPE: 5.317%. These are existing artifact metrics, not accuracy measured on this sample hospital.
- The UI displays the warning that this hospital identifier is outside the exported training categories and requires local shadow validation. Prediction intervals are not implemented (API interval fields are null).

## Confirmed issues and incomplete workflows

| Priority | Finding and evidence | Recommended correction |
| --- | --- | --- |
| High | Forecast, simulation, and optimisation are separate flows. `frontend/healthflow/src/pages.tsx:104` and `:109` send hard-coded `LOCAL_HOSPITAL` scenarios; the 4,411 forecast is not passed into resource planning. | Add editable scenario inputs and explicitly connect hospital forecast, capacity snapshot, simulation, and optimisation. |
| High | Important model factors are incorrectly formatted as percentages (`pages.tsx:92`). The exported permutation importance uses `neg_mean_absolute_error` (`backend/scripts/build_main_model_notebook.py:447`); a value of 2571.828997986333 becomes 257182.9%. | Show permutation importance as change in MAE with clear units; do not present it as a percentage or patient-specific explanation. |
| Medium | Candidate benchmark values appear as dashes in screenshot 03. UI reads `validation_wape`/`validation_mae` (`pages.tsx:122`); the CSV/API fields are `wape`/`mae`. | Map the real fields and use null checks so zero values remain visible. |
| Medium | Header always says “Model ready” (`frontend/healthflow/src/App.tsx:64`). | Derive the badge from `/model/status`, including loading and failure states. |
| Medium | Capacity and policy pages only list records; there are no UI controls to add snapshots or policies. Optimisation has no UI approval action, despite backend endpoints existing. | Complete those frontend forms/actions and expose their loading, success, and failure states. |
| Medium | Future history is accepted as “completed” history. A read-only schema probe accepted months through January 2091. | Reject current/incomplete and future reporting months, or provide a clearly separated retrospective/test mode. |
| Medium | Intelligence follow-up schema declares `conversation_id: int` (`backend/app/schemas.py:96`) while the API generates UUID strings. Reproduced rejection of a returned UUID. | Use the same UUID/string type across request schema, persistence, and frontend. |
| Medium | Equally relevant policy documents cause `policy_context()` to compare document objects while sorting (`backend/app/services/intelligence.py:35`). A read-only probe reproduced a TypeError. | Sort with an explicit numeric score key and deterministic tiebreaker. |
| Medium | Capacity validation accepts occupied beds greater than staffed beds. Read-only probe accepted 150 occupied / 100 staffed. | Reject inconsistent snapshots or explicitly model overflow capacity. |
| Environment | Ollama/qwen3:8b was unavailable. | Start/configure the local model service, then verify normal generation and error handling. |
| Verification tooling | ESLint skips TSX; documented root pytest command does not work as written. | Add TypeScript lint support and fix test configuration or documentation. |

Several page requests also lack user-visible error handling; normal successful flows were exercised, but service failure/recovery coverage remains incomplete. No claim of production, clinical, security, load, or statistical validation is made by this functional review.

## Screenshots

These are genuine Chromium captures of the running local frontend and real backend responses. No UI values were mocked or edited for the images. Screenshot 03 intentionally preserves the current benchmark display defect.

1. [Login](01-login.png)
2. [Overview dashboard](02-overview.png)
3. [Model performance](03-model-performance.png)
4. [Digital twin simulation result](04-digital-twin-simulation.png)
5. [Resource optimisation recommendation](05-resource-optimisation.png)
6. [Input data entered in the frontend](06-forecast-input-data.png)
7. [Prediction returned in the frontend](07-forecast-prediction-result.png)

## Reproduction and scope

The local app was started at `http://localhost:5173`, with the API at `http://localhost:8000`. Desktop/browser control was unavailable, so a separate Playwright/Chromium test harness captured the app. The first harness attempt read the asynchronous CSV import before React finished updating; the harness was corrected to wait for the imported values and the full rerun passed. This was a test timing issue, not a CSV import failure.

Application source and model artifacts were not changed. The review created local test forecast, simulation, optimisation, and degraded intelligence records in the existing development database; no recommendation was approved. The services were left running for local inspection.

Evidence files: `verification-results.json`, `backend-probes.json`, `prediction-input.json`, `prediction-output.json`, and the copied `hospital_prediction_test.csv`. The reproducible browser harness is `browser-tools/audit.cjs`; read-only defect reproductions are in `backend-probes.py`.
