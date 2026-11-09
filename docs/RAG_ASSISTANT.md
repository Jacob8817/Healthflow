# HealthFlow Groq + RAG assistant

Implemented 9 November 2026. The assistant now uses Groq for generation and tool selection, a local BGE-small English embedding model (384 dimensions), persistent SQL policy chunks and cosine similarity combined with keyword overlap. It does not require Ollama. Exact vector search is suitable for this small policy library; it is not an ANN service or a complete enterprise document platform.

## Configuration and startup

The supplied key is stored only in the untracked `backend/.env.local`. It is excluded from Git and Docker build context and is not returned through the API. Because the key was posted in chat, rotate it in Groq and replace `GROQ_API_KEY` locally. Do not copy it into project context files or frontend variables.

```dotenv
GROQ_API_KEY=your_replacement_key
GROQ_MODEL=openai/gpt-oss-120b
RAG_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

From `F:\projhosp\backend`, start the backend as usual:

```powershell
& F:\projhosp\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

From `F:\projhosp\frontend\healthflow`, use `npm run dev`. Open http://localhost:5173/intelligence after signing in. The service badge checks Groq model access and caches status for 60 seconds. Successful status does not guarantee remaining generation quota. Restart the backend after changing the key; `.env` changes alone may not trigger reload.

On another checkout, install `backend/requirements.txt` including `fastembed==0.9.1`. The embedding model downloads on first use and is cached under `backend/.rag_cache`. The current workstation's model is downloaded, checksum-verified and operational. The cache is local and excluded from source control/container images. Docker users supply their key in the root Compose environment; Docker deployment was not verified in this change.

## RAG and documents

Policy library supports pasted text, UTF-8 TXT/Markdown and text-based PDFs (10 MB upload limit, 200 PDF pages, 200,000 extracted characters). Scanned PDFs need OCR before upload. Documents are split into overlapping passages without crossing PDF pages; PDF page numbers are preserved. Title and passage text are embedded locally. Vectors, text, document identity and model identity are stored in the application database. Retrieval combines semantic cosine similarity with lexical overlap and returns up to four passages.

Duplicate content is deduplicated by SHA256. Indexing failure rolls back the new document instead of saving a falsely indexed record. Existing unindexed policies are indexed when retrieval runs. The backend checks embedding-model identity and reindexes mismatches. Documents are shared across the installation, as the existing policy library was; there is no per-hospital policy ACL, approval/version workflow or automatic deletion UI.

`docs/HEALTHFLOW_ASSISTANT_REFERENCE.md` was indexed as **HealthFlow system reference (not clinical policy)**. It explains actual bed semantics, forecast inputs, capacity formulas and limitations. It is software documentation, not invented clinical guidance or an approved hospital policy. Add real approved references separately when authorised.

Sources include document/passage IDs, title, page where applicable, excerpt and source reference. The UI lists retrieved evidence; retrieval does not guarantee that every passage was cited in the answer. Unknown generated citation IDs are replaced with a source-unavailable marker. This validates source membership, not semantic entailment of every sentence. Language-model errors remain possible.

## Hospital tools

All queries use the selected hospital from the authenticated request. The model cannot supply another hospital ID or arbitrary SQL. Accounts still share the existing installation; there are no new per-hospital user grants.

| Tool | Behaviour |
|---|---|
| `hospital_snapshot` | Current recorded beds/wards, emergency counts, latest three forecasts and up to twelve monthly resource records; timestamps and data origin included. |
| `search_policies` | Semantic + keyword search over the shared indexed library. |
| `staffing_equipment_tasks` | Up to 20 shifts, 30 equipment rows and 20 tasks for this hospital; bounded records, not lifetime totals. |
| `saved_capacity_plans` | Latest three plans with assumptions, recommendations and decision status. |
| `run_forecast` | Existing trained pipeline using latest saved, validated input history. Unsaved preview, with source forecast ID, target month and historical-target flag. |
| `preview_capacity` | Existing simulator and optimiser, actual target-month calendar days, current staffed inventory and matching-month resources. Unsaved preview with assumptions; no allocation or approval. |

The last two tools require admin/planner role **and** the frontend checkbox “Enable forecast and scenario previews for this message”. Ask explicitly for the calculation. Server dispatch also enforces the role/checkbox, tool allow-list, argument schema and hospital binding. There is no approval, bed-editing, arbitrary-code or arbitrary-URL tool.

Normal Demand forecast submissions now persist their validated history in `hospital_forecast_histories`. Older saved predictions have no recoverable input rows: submit their monthly history through Demand forecast again. The assistant never fills missing history with invented data. The historical sample CSV was resubmitted during verification and predicts 4,411 admissions for August 2026. Date flags make this a retrospective preview as of November 2026.

Capacity previews need a saved forecast ID and a staffing resource record for that forecast month. Default scenario assumptions remain 20-hour average stay, 85% occupancy, four staff-hours per admission, up to 100 extra beds and 10,000 extra staff-hours. Preview output does not save a plan. Use the normal Capacity planning page to create a plan for review. Simulation starts empty, uses twenty seeded replications, and does not model ward routing, initial inpatients or equipment/skill constraints.

## Conversation, privacy and failures

Conversations are persisted and bound to both authenticated user and selected hospital using a separate scope table. Old unscoped conversations cannot be resumed through the new API. The last six messages are supplied as conversational context; there is no unlimited memory. Browser localStorage keeps the conversation ID, not the API key. A new conversation clears the active ID, not the database history.

Every answer receives a fresh hospital snapshot and policy search; additional tools are model-selected. The agent is bounded to four completion rounds and six executed tool calls, with repeated tool results reused within the turn. Tool traces and assistant audit events are persisted. Documents are treated as untrusted content; permission enforcement is in backend code, not just prompts.

Only selected record summaries and retrieved excerpts are sent to Groq, but those contents leave the machine. Local embedding storage does not mean fully local processing. The prototype uses synthetic hospital records and software reference text. Do not infer that this implementation is approved for confidential production hospital data.

Missing keys, invalid credentials, quota exhaustion, connection failures and provider failures receive distinct messages. Embedding/retrieval failure is disclosed; the assistant may still answer from hospital evidence. There is no silent fallback to made-up forecasts or to a different external provider. Free-tier rate limits still apply; no unlimited-availability guarantee is made. Computation cards show verified forecast/scenario results independently of generated prose.

## Changed code

- `app/services/retrieval.py`: passage indexing and hybrid retrieval.
- `app/services/agent_tools.py`: hospital-scoped allow-listed tools.
- `app/services/intelligence.py`: Groq requests, bounded tool loop, evidence/citation handling.
- `app/api/router.py`: chat/history/document routes and saved forecast history.
- `app/api/operations.py`: shared capacity calculation for saved plans and unsaved previews.
- `app/db/models.py`: additive policy chunk, conversation scope and history tables.
- `src/intelligence.tsx`: conversation UI, sources/tool outputs, previews toggle, document upload.
- `backend/tests/test_rag_agent.py`: eleven additional tests; total suite 24 tests passed.

TypeScript and frontend build checks passed during development. Real provider, semantic retrieval, forecast and capacity verification evidence/screenshots are kept under `artifacts/rag-agent`; consult those results rather than assuming every possible conversation is tested.

Repository packaging: `.env` files contain safe defaults/placeholders. Keep live credentials in ignored `.env.local`; backend settings load it after `.env`. The trained `.joblib` is tracked with Git LFS.
