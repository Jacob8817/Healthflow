# HealthFlow

HealthFlow is a local-first NHS emergency-demand forecasting and operational planning application. It serves the existing exported Random Forest pipeline without retraining, validates its 47-feature contract, simulates aggregate patient flow, generates approval-gated capacity recommendations, and offers Groq-backed Operations Intelligence with local policy retrieval.

## Clone the complete project

The trained forecasting pipeline is stored with Git LFS. Install Git LFS before cloning:

```powershell
git lfs install
git clone https://github.com/Jacob8817/Healthflow.git
cd Healthflow
git lfs pull
```

The repository includes source, notebooks with charts, model metadata, the NHS aggregate dataset snapshot, sample inputs, documentation and screenshots. Virtual environments, node modules, local databases, embedding caches and private environment overrides are excluded.

## Environment files

Tracked root and backend `.env` files contain development defaults and empty/placeholder secrets. Put the actual Groq key in **`backend/.env.local`** for local development; the backend loads it after `backend/.env`. Never commit real keys. The assistant's local embedding model downloads on first use.

```dotenv
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-120b
```

## Run with containers

1. Create an ignored root `.env.local` from `.env.example` and configure its secrets.
2. Run `docker compose --env-file .env.local up --build`.
3. Open `http://localhost:3000`.

The API is available at `http://localhost:8000`, with interactive documentation at `/docs`. The development login is `admin@healthflow.local` / `ChangeMe123!`. See `docs/RAG_ASSISTANT.md` for the Groq assistant. Docker uses a separate PostgreSQL database and will not contain your local SQLite records.

## Run locally

From `backend`, create a virtual environment, install `requirements.txt` and `requirements-dev.txt`, then run:

```powershell
uvicorn app.main:app --reload
```

From `frontend/healthflow`:

```powershell
npm install
npm run dev
```

The model artifact and its metadata remain the source of truth. Forecast readiness returns a degraded state if validation or loading fails. Use the processed data importer from the backend directory:

```powershell
python -m app.cli.import_nhs_forecast_data --dry-run
python -m app.cli.import_nhs_forecast_data
```

## Verification

```powershell
pytest backend/tests
cd frontend/healthflow
npm run build
```

Forecasts are for aggregate operational planning only and are not patient-level or clinical advice. Optimization recommendations require explicit administrator approval.

## Operations assistant

See [RAG assistant setup and tools](docs/RAG_ASSISTANT.md) and [complete project context](docs/CHATGPT_PROJECT_CONTEXT.md). The assistant uses Groq with local semantic policy retrieval and hospital-scoped tools. Backend secrets belong only in an untracked environment file.
