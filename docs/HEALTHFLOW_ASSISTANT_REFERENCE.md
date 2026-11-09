# HealthFlow assistant reference — implementation, not clinical policy

Source: HealthFlow repository, 9 November 2026. This is a software workflow reference. It is not a hospital-approved clinical policy and does not establish escalation thresholds or treatment rules.

## Hospital data and beds
HealthFlow is for hospital staff. Hospital records are entered by staff; no live EHR, ADT or roster connection exists. Always distinguish a record's timestamp from the time it was retrieved. An absent resource, queue or shift record is unknown, not zero. The City General Hospital development workspace contains synthetic sample records.

Beds are grouped schematically by floor and ward. Statuses are available, occupied, reserved, cleaning and blocked. An immediately available bed must be staffed. Monthly operational capacity counts staffed non-blocked beds, including occupied, reserved and cleaning beds. This capacity count is not the same as the number of beds immediately free. New beds are blocked and unstaffed until staff confirm their state. The assistant cannot change bed states.

## Emergency and priorities
The emergency snapshot records counts awaiting assessment, awaiting a bed and staff-assessed high/medium/low priority counts. No patient-level records or automated triage model are connected. The assistant must not infer patient priority or recommend treatment. Operational task priorities routine/urgent are not patient triage categories.

## Forecast model and input history
Demand forecast requires 13–120 consecutive completed months: month, total_ae_attendances, emergency_admissions, attendances_under_4_hours, decision_to_admit_waits_over_4_hours. Current/future input months are rejected. Staff submit these through the Demand forecast screen or its CSV importer. New submissions now save the validated input history with their forecast. Legacy forecast records do not contain their original input history; submit the history again before asking the assistant to rerun the model.

The trained Random Forest predicts aggregate emergency admissions for the month after the last input month. Historical inputs produce a retrospective forecast, not a forecast automatically anchored to today's date. The assistant's forecast tool calls this trained pipeline with saved inputs. It never creates synthetic monthly values to fill gaps. Tool results are unsaved previews and carry their source input forecast ID. The normal Demand forecast screen saves results for later planning. No retraining occurs. Future ward-level, hourly, discharge or length-of-stay predictions are not implemented.

## Capacity scenarios and assumptions
Capacity planning uses a saved hospital forecast, current staffed/non-blocked bed inventory and monthly available staff hours for the forecast target month. The normal screen saves a plan for administrator review. The assistant's capacity tool returns a preview without saving a plan or allocating resources.

Default assumptions: average stay 20 hours, target occupancy 85%, staff requirement four hours per admission, up to 100 extra beds and 10,000 extra staff-hours. Staff can request other values within validation limits. State assumptions in every scenario answer.

Required bed-hours = admissions × average stay hours / target occupancy. Available bed-hours = staffed operational beds × target-month days × 24. Required staff-hours = admissions × staff-hours per admission. Extra beds are available for the entire target month. Calendar months have their actual number of days. The illustrative costs are £500 per extra bed-day and £45 per extra staff-hour, not verified procurement prices.

The simulation uses twenty seeded replications, starts empty, and simulates the forecast cohort. Occupancy is time-weighted. Wait statistics cover admissions that obtained a bed; end-of-month waiting counts are separate. Existing inpatients, elective activity, detailed ward routing, equipment and skill constraints are not modelled. A capacity preview uses present recorded inventory even if the chosen forecast month is historical.

## Staffing, equipment, tasks and approvals
Shift gaps are arithmetic differences between recorded required and available staffing. Partial shift records do not replace the monthly staff-hour budget. Equipment stocks are context and are not optimiser constraints. Staff must mark unusable beds appropriately. Tasks are staff-owned follow-up records. Recommendations await administrator approval; approval records a decision but does not execute bed/staff allocation. The assistant has no approval or record-editing tools.

## Assistant and document evidence
The assistant combines Groq generation, locally computed BGE-small embeddings, stored policy passages, semantic/keyword retrieval, and hospital-scoped backend tools. Only retrieved excerpts and selected record summaries are sent to Groq. Documents are shared across this installation. An uploaded document is not automatically an approved hospital policy. Answers should cite the actual retrieved passage IDs and hospital/tool evidence. When evidence is absent, say what is missing. Free-tier quotas may delay or prevent generation; no successful action should be claimed after a failed tool.
