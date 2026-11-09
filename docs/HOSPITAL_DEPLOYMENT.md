# HealthFlow hospital deployment gates

The current Compose stack is a development and controlled-pilot environment. It must not be connected to a live hospital network or used to direct care until every gate below has a named owner and recorded approval.

## 1. Define and approve intended use

- Keep the intended use limited to aggregate operational planning unless a new regulatory assessment approves a broader purpose.
- Document intended users, excluded uses, data inputs, forecast horizon, failure states, and the required human review.
- Obtain an MHRA classification opinion on whether the final intended purpose makes the product Software as a Medical Device.
- Prohibit patient-level, diagnostic, treatment, triage, or autonomous resource-allocation use in policy, training, UI, and contracts.

## 2. Clinical safety

- Appoint a qualified Clinical Safety Officer.
- Complete the applicable DCB0129 manufacturer process and provide the clinical risk management plan, hazard log, safety case report, and safety incident process.
- The adopting Trust must complete its local DCB0160 deployment safety case.
- Include hazards for stale or missing source data, hospital-identifier mismatch, model drift, unexpectedly low or high forecasts, unavailable services, misunderstood uncertainty, and over-reliance on generated text.

## 3. Information governance

- Complete DTAC using the current form and guidance.
- Complete a Data Protection Impact Assessment and data-flow map with the Trust DPO/Caldicott Guardian.
- Establish controller/processor roles, lawful basis, retention, deletion, subject-rights handling, and a signed data-processing agreement.
- Complete the relevant Data Security and Protection Toolkit assurance.
- Do not ingest patient-identifiable data until the approved data flow, minimisation, access controls, and retention rules are implemented.

## 4. Identity and security

- Replace local passwords with the Trust identity provider using OIDC/SAML, MFA, conditional access, group-to-role mapping, and joiner/mover/leaver processes.
- Keep access tokens out of browser persistent storage; use a secure backend-for-frontend session with `HttpOnly`, `Secure`, `SameSite` cookies and CSRF protection.
- Use managed secrets, TLS end to end, network segmentation, egress allow-lists, a WAF/reverse proxy, vulnerability scanning, SBOMs, signed images, patch SLAs, penetration testing, and independent security review.
- Send tamper-evident authentication, data access, forecast, simulation, approval, policy, and administrator audit events to the Trust SIEM.

## 5. Production platform

- Run PostgreSQL as a managed or HA service with encryption, tested point-in-time recovery, immutable backups, and restore exercises.
- Use versioned Alembic migrations; do not create or modify production schema automatically at application startup.
- Deploy redundant API and frontend instances with resource limits, health checks, graceful shutdown, alerting, central logs, metrics, traces, and documented SLOs.
- Keep Ollama isolated on approved hospital infrastructure. Pin and checksum models; prohibit outbound model-provider traffic; test prompt-injection and policy-document poisoning controls.
- Separate development, test, pilot, and production accounts, networks, secrets, databases, and model artifacts.

## 6. Model assurance

- Perform silent prospective validation using the Trust's own hospital data before operational use.
- Approve performance thresholds by hospital site and season, not only nationally. Record WAPE, bias, under-forecast risk, missingness, and site variation where applicable.
- Add data-quality gates, freshness alerts, out-of-distribution checks, drift monitoring, forecast reconciliation, model rollback, and a defined revalidation/change-control process.
- Never update the production artifact without a new immutable version, validation report, safety review, approval, and rollback plan.

## 7. Pilot and operations

- Start in shadow mode: forecasts visible to an evaluation team but not used to alter staffing or beds.
- Predefine pilot endpoints, success and stop criteria, incident escalation, downtime procedures, and a manual fallback.
- Run usability and accessibility testing with intended hospital users.
- Train users on limitations and require explicit human approval for any recommendation.
- Establish 24/7 ownership where required, support SLAs, major-incident response, business continuity, disaster recovery, and post-market/performance surveillance.

## Release decision

Production release requires written sign-off from the Trust service owner, clinical safety officer, DPO/information governance, cyber security, infrastructure/operations, model owner, and procurement/vendor management. A green application health check is not evidence of clinical, regulatory, or organisational approval.
