# HealthFlow staff portal

Implemented 8 November 2026 in the existing React/FastAPI project. The app is available locally at `http://localhost:5173`, with its API at `http://localhost:8000`.

## Staff workflow

1. Sign in with an existing staff account. Login fields are no longer prefilled with administrator credentials.
2. Create a hospital workspace or, in development, choose **Load demonstration workspace**. Demonstration records are labelled throughout the UI. A real workspace starts empty.
3. Add floors/wards and bed counts. New beds start blocked and unstaffed until confirmed. Select a bed to maintain availability, occupancy, reservation, cleaning, staffing, capability context, and an operational note. Concurrent changes are rejected instead of overwritten silently.
4. Record aggregate emergency queue counts and already-assessed clinical priority categories. No patient-level triage prediction or patient record collection is implemented.
5. Import 13–120 consecutive completed months into **Demand forecast**. The selected workspace supplies hospital identity. Forecasts are saved to the existing forecast history.
6. Save a monthly staffing budget for the forecast's target month. Shift coverage by date/team and equipment stock by type/location can be maintained separately.
7. Run **Capacity planning**. The server retrieves the chosen hospital forecast, current staffed/non-blocked inventory, and matching-month staffing record. Editable assumptions determine bed-hours and staff-hours required. The month length is used consistently by the simulator and optimiser.
8. Review the result in **Action queue**. Administrators can approve or reject a feasible pending plan. A decision is recorded and audited; no staff or bed allocation is executed. Assign operational tasks to an owner and track their progress.

## Navigation and access

The primary navigation is Hospital overview, Beds & wards, Emergency flow, Demand forecast, Capacity planning, Staffing & equipment, and Action queue. The support area contains Operations assistant and Policy library.

Model benchmarks, WAPE, R², and technical readiness are in **Administration → Model diagnostics**, with server-side administrator-only access to metrics/benchmarks. The misleading always-ready badge has been removed. Normal users see operational data, reporting periods, data provenance, and recorded timestamps.

The existing roles are retained: `admin` and `planner` can maintain operational records and generate forecasts/scenarios; `viewer` can inspect operational data; only `admin` can review recommendations and access model diagnostics. All accounts belong to the same installation. Per-hospital access grants and account provisioning are not part of this change.

## Data and planning semantics

- New additive tables: hospitals, wards, beds, emergency snapshots, monthly resource records, staff shifts, equipment stock, and operational tasks. The project's existing startup schema-creation mechanism creates them. No previous forecast or model artifact was replaced.
- Bed changes use optimistic version checking and audit events. Other operational mutations are also audited.
- The layout is a schematic grouping of wards/floors, not an imported architectural floor plan.
- Current staffed operational capacity includes occupied, reserved, cleaning, and available staffed beds; blocked or unstaffed beds are excluded. This is capacity across a monthly scenario, not the number of beds immediately free.
- Bed requirement = forecast admissions × assumed average stay / target occupancy. It is compared to staffed beds × hours in the forecast month.
- Additional bed cost uses £500 per bed-day over the entire target month; staff cost uses £45 per additional hour. These are illustrative assumptions, not hospital procurement prices.
- Simulation occupancy is now time-weighted. Wait metrics cover patients who obtained a bed during the simulation; the remaining end-of-month queue is shown separately. Twenty deterministic seeded replications start from an empty system and model the forecast cohort only. Initial patients, elective admissions, ward-specific routing, and transfer constraints are not simulated.
- Shift staffing gaps are arithmetic comparisons of recorded available vs required staff. Partial shift records do not automatically overwrite the monthly budget. Changing a shift's date/team/key creates a separate record; saving the same key updates it.
- Equipment stock is recorded operational context. The current optimiser does not model skill-specific staffing or equipment-dependent constraints. Staff must block any unusable beds.
- Refresh loads the latest server records. No live hospital EHR/ADT/roster feed is connected, and these records are not labelled live.
- The existing model still predicts next-month aggregate admissions only. Hourly forecasts, ward-specific models, discharge prediction, and clinical-priority inference require additional data and separate validation and were not fabricated.

## Verification

- Frontend production build and TypeScript check passed.
- **13 backend tests passed**, covering persistent inventory, bed status validation, concurrent edits, cross-hospital record checks, role enforcement, resource upserts, emergency validation, shift/equipment updates, calendar-month planning units, infeasible plans, and administrator review.
- **10 browser verification groups passed**, including real login, database-backed inventory edits across reload, emergency/resources/shift/equipment entry, CSV import, real forecast generation, linked planning, action updates, corrected admin benchmarks, and mobile navigation. No uncaught JavaScript errors occurred in the tested flows.
- `pytest.ini` now permits running the backend suite from the project root. Dependency deprecation warnings remain.
- Sample run: **4,411 admissions for August 2026** from July 2025–July 2026 inputs. With 116 staffed operational beds, 15,000 monthly staff hours, 20-hour average stay, 85% target occupancy, and 4 staff-hours/admission, the plan recommends **24 additional beds and 2,644 additional staff hours**. It remains pending review. The current inventory is used against the historical sample month as an explicitly labelled scenario.

The local database contains labelled demonstration records and verification-created forecasts/scenarios. A pre-change database and frontend backup is retained under `artifacts/staff-portal-implementation/before`. Screenshot and test evidence is under `artifacts/staff-portal-implementation`.

## Commands

```powershell
# From project root
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# From frontend/healthflow
npx --no-install tsc --noEmit
npm run build
```

The development login remains the one documented in the project README. Deployment assurance requirements remain in `HOSPITAL_DEPLOYMENT.md`; this implementation and its screenshots do not replace local operational validation.
