from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.ai.forecasting.errors import ForecastingError
from app.api.deps import (
    forecast_service, get_current_user, get_db, intelligence_service,
    optimisation_service, require_roles, simulation_service,
)
from app.core.security import create_access_token, verify_password
from app.db.models import (
    AuditLog, CapacitySnapshot, ForecastRun, OperationsIntelligenceConversation,
    OperationsIntelligenceMessage, OptimisationPlan, PolicyDocument,
    SimulationRun, User, Hospital, HospitalForecastHistory, AgentConversationScope, OperationsIntelligenceToolCall, PolicyChunk,
)
from app.schemas import (
    ApprovalRequest, CapacityIn, HospitalForecastRequest, IntelligenceRequest,
    OptimisationRequest, PolicyIn, SimulationRequest, Token, UserOut,
)

router = APIRouter()


def _finite_json(value):
    """Convert exported NumPy/JSON metrics into strict RFC-compliant JSON."""
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _finite_json(value.item())
    return value


@router.post("/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return Token(access_token=create_access_token(str(user.id), user.role))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/forecasts/hospital")
def create_forecast(
    payload: HospitalForecastRequest,
    service=Depends(forecast_service),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "planner")),
):
    try:
        result = service.forecast_hospital(
            payload.hospital_identifier, payload.hospital_name,
            [row.model_dump() for row in payload.history],
        )
    except (ValueError, ForecastingError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    run = ForecastRun(
        id=result["forecast_run_id"], hospital_identifier=result["hospital"]["identifier"],
        feature_month=result["feature_month"], target_month=result["target_month"],
        raw_prediction=result["raw_prediction"],
        displayed_prediction=result["predicted_emergency_admissions"],
        model_version=result["model"]["version"], warnings=result["warnings"],
    )
    db.add(run)
    db.flush()
    db.add(HospitalForecastHistory(forecast_id=run.id, hospital_id=payload.hospital_identifier.upper(),
                                  history=[r.model_dump() for r in payload.history]))
    db.commit()
    return result


@router.get("/forecasts/history")
def forecast_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(ForecastRun).order_by(desc(ForecastRun.created_at)).limit(100)).all()


@router.get("/model/status")
def model_status(request: Request, user: User = Depends(get_current_user)):
    return request.app.state.model_loader.status()


@router.get("/model/metrics")
def model_metrics(request: Request, user: User = Depends(require_roles("admin"))):
    bundle = request.app.state.model_loader.load()
    return _finite_json({"validation": bundle.validation_metrics, "test": bundle.test_metrics})


@router.get("/model/benchmarks")
def model_benchmarks(request: Request, user: User = Depends(require_roles("admin"))):
    path = request.app.state.model_loader.model_dir / "benchmark_results.csv"
    import pandas as pd
    return _finite_json(pd.read_csv(path).to_dict("records"))


@router.get("/capacity")
def capacity(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(CapacitySnapshot).order_by(desc(CapacitySnapshot.snapshot_month))).all()


@router.post("/capacity")
def save_capacity(
    payload: CapacityIn, db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "planner")),
):
    row = CapacitySnapshot(
        hospital_identifier=payload.hospital_identifier.upper(), snapshot_month=payload.snapshot_month,
        beds_total=payload.staffed_beds, beds_occupied=payload.occupied_beds,
        staff_available=payload.available_staff_hours,
        staff_required=payload.required_staff_hours,
        equipment_available=payload.equipment_available, notes=payload.notes,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.post("/simulations")
def run_simulation(
    payload: SimulationRequest, service=Depends(simulation_service),
    db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "planner")),
):
    result = service.run(**payload.model_dump(exclude={"hospital_identifier"}))
    run = SimulationRun(id=str(uuid.uuid4()), hospital_identifier=payload.hospital_identifier.upper(),
                        scenario=payload.model_dump(mode="json"), result=result)
    db.add(run); db.commit()
    return {"id": run.id, **result}


@router.get("/simulations")
def simulations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(SimulationRun).order_by(desc(SimulationRun.created_at))).all()


@router.post("/optimisations")
def optimise(
    payload: OptimisationRequest, service=Depends(optimisation_service),
    db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "planner")),
):
    result = service.solve(payload.model_dump())
    plan = OptimisationPlan(
        id=str(uuid.uuid4()), hospital_identifier=payload.hospital_identifier.upper(),
        input_data=payload.model_dump(), recommendation=result,
        status=result["status"],
    )
    db.add(plan); db.commit()
    return {"id": plan.id, **result}


@router.get("/optimisations")
def optimisations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(OptimisationPlan).order_by(desc(OptimisationPlan.created_at))).all()


@router.post("/optimisations/{plan_id}/approval")
def approve_plan(
    plan_id: str, payload: ApprovalRequest, db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    plan = db.get(OptimisationPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.status != "pending_approval":
        raise HTTPException(409, "Only a pending feasible plan can be reviewed")
    plan.status = payload.decision
    plan.approved_by = user.id
    db.add(AuditLog(action=f"optimisation.{payload.decision}", actor_id=user.id,
                    details={"plan_id": plan_id, "note": payload.note}))
    db.commit()
    return {"id": plan.id, "status": plan.status}


@router.get("/operations-intelligence/status")
def intelligence_status(service=Depends(intelligence_service), user: User = Depends(get_current_user)):
    return service.status()


@router.post("/operations-intelligence")
def intelligence(
    payload: IntelligenceRequest, request: Request, service=Depends(intelligence_service),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.services.agent_tools import HospitalTools
    if db.get(Hospital, payload.hospital_id) is None:
        raise HTTPException(404, "Hospital not found")
    if payload.allow_compute and user.role not in ("admin", "planner"):
        raise HTTPException(403, "Only planners and administrators can run forecast/scenario tools")
    conversation = db.get(OperationsIntelligenceConversation, payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id:
        scope = db.get(AgentConversationScope, payload.conversation_id)
        if not conversation or conversation.user_id != user.id or not scope or scope.hospital_id != payload.hospital_id:
            raise HTTPException(404, "Conversation not found for this hospital and user")
    if not conversation:
        conversation = OperationsIntelligenceConversation(id=str(uuid.uuid4()), user_id=user.id, title=payload.message[:80])
        db.add(conversation); db.flush()
        db.add(AgentConversationScope(conversation_id=conversation.id, hospital_id=payload.hospital_id)); db.flush()
    history = list(reversed(db.scalars(select(OperationsIntelligenceMessage).where(
        OperationsIntelligenceMessage.conversation_id == conversation.id).order_by(OperationsIntelligenceMessage.id.desc()).limit(6)).all()))
    tools = HospitalTools(db, payload.hospital_id, user, request, service.retriever, payload.allow_compute)
    result = service.answer(payload.message, tools, history)
    db.add(OperationsIntelligenceMessage(conversation_id=conversation.id, role="user", content=payload.message))
    db.add(OperationsIntelligenceMessage(conversation_id=conversation.id, role="assistant", content=result["answer"], structured_response=result))
    for call in result.get("tools", []):
        db.add(OperationsIntelligenceToolCall(conversation_id=conversation.id, tool_name=call["name"], arguments=call["arguments"], status=call["status"]))
    db.add(AuditLog(action="assistant.answered",actor_id=user.id,details={"hospital_id":payload.hospital_id,"conversation_id":conversation.id,"status":result["status"],"tools":[t["name"] for t in result.get("tools",[])]}))
    db.commit()
    return {"conversation_id":conversation.id,"hospital_id":payload.hospital_id,**result}


@router.get("/operations-intelligence/conversations/{conversation_id}")
def conversation_history(conversation_id: str, hospital_id: str, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    conversation = db.get(OperationsIntelligenceConversation,conversation_id)
    scope = db.get(AgentConversationScope,conversation_id)
    if not conversation or conversation.user_id != user.id or not scope or scope.hospital_id != hospital_id:
        raise HTTPException(404,"Conversation not found")
    return db.scalars(select(OperationsIntelligenceMessage).where(OperationsIntelligenceMessage.conversation_id == conversation_id).order_by(OperationsIntelligenceMessage.id)).all()


@router.get("/policies")
def policies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(PolicyDocument).order_by(desc(PolicyDocument.created_at))).all()


def store_policy(payload, db, user, service, filename=None):
    checksum = hashlib.sha256(payload.content.encode()).hexdigest()
    existing = db.scalar(select(PolicyDocument).where(PolicyDocument.checksum == checksum))
    if existing:
        return existing
    row = PolicyDocument(title=payload.title, filename=filename or f"{checksum[:12]}.txt",
                         checksum=checksum, text_content=payload.content, source=payload.source)
    try:
        db.add(row); db.flush()
        chunks = service.retriever.index(db,row)
        db.add(AuditLog(action="policy.indexed",actor_id=user.id,details={"document_id":row.id,"chunks":chunks}))
        db.commit(); db.refresh(row)
    except Exception:
        db.rollback()
        raise HTTPException(503,"Policy indexing failed. Check the local embedding model/cache and retry; the document was not saved.") from None
    return row


@router.post("/policies")
def add_policy(payload: PolicyIn, db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "planner")), service=Depends(intelligence_service)):
    return store_policy(payload,db,user,service)


@router.post("/policies/upload")
async def upload_policy(file: UploadFile=File(...), title: str=Form(...), source: str=Form(""),
    db: Session=Depends(get_db), user: User=Depends(require_roles("admin","planner")), service=Depends(intelligence_service)):
    import io
    from pathlib import Path
    from pypdf import PdfReader
    from pydantic import ValidationError
    from starlette.concurrency import run_in_threadpool
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413,"Use a document smaller than 10 MB")
    filename = Path(file.filename or "document.txt").name
    suffix = Path(filename).suffix.lower()
    def extract():
        if suffix == '.pdf':
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 200:
                raise ValueError('Use an unencrypted PDF with at most 200 pages')
            # A trailing form-feed retains page 1 even for a single-page PDF.
            return '\f'.join(page.extract_text() or '' for page in reader.pages) + '\f'
        if suffix in ('.txt','.md'):
            return raw.decode('utf-8-sig')
        raise ValueError('Supported formats: PDF, TXT, MD')
    try:
        content = await run_in_threadpool(extract)
        payload = PolicyIn(title=title,source=source,content=content)
        if len(content.strip()) < 10:
            raise ValueError('No readable text. Scanned PDFs need OCR before upload.')
    except (ValueError, UnicodeError, ValidationError) as exc:
        raise HTTPException(422,str(exc)) from None
    except Exception:
        raise HTTPException(422,'Unable to extract text from this document.') from None
    return await run_in_threadpool(store_policy,payload,db,user,service,filename)


@router.get("/policies/index/status")
def policy_index_status(db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    from sqlalchemy import func
    return {"documents":db.scalar(select(func.count()).select_from(PolicyDocument)),
            "chunks":db.scalar(select(func.count()).select_from(PolicyChunk)),"scope":"Shared across this installation"}
