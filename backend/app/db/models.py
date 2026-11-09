from __future__ import annotations
from datetime import date
from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="HealthFlow User")
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(40), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    first_month: Mapped[str | None] = mapped_column(String(7))
    latest_month: Mapped[str | None] = mapped_column(String(7))
    continuity_warning: Mapped[bool] = mapped_column(Boolean, default=False)


class ProviderMonthlyMetric(Base, TimestampMixin):
    __tablename__ = "provider_monthly_metrics"
    __table_args__ = (UniqueConstraint("provider_code", "reporting_month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_code: Mapped[str] = mapped_column(ForeignKey("providers.code"), index=True)
    reporting_month: Mapped[str] = mapped_column(String(7), index=True)
    total_ae_attendances: Mapped[float | None] = mapped_column(Float)
    emergency_admissions: Mapped[float | None] = mapped_column(Float)
    attendances_under_4_hours: Mapped[float | None] = mapped_column(Float)
    waits_over_4_hours: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200), default="NHS England")


class ForecastRun(Base, TimestampMixin):
    __tablename__ = "forecast_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_identifier: Mapped[str] = mapped_column("provider_code", String(16), index=True)
    feature_month: Mapped[str] = mapped_column(String(7))
    target_month: Mapped[str] = mapped_column(String(7))
    raw_prediction: Mapped[float] = mapped_column(Float)
    displayed_prediction: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(100))
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    model_class: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(100), unique=True)
    artifact_filename: Mapped[str] = mapped_column(String(300))
    artifact_checksum: Mapped[str] = mapped_column(String(64))
    feature_schema: Mapped[dict] = mapped_column(JSON)
    validation_metrics: Mapped[dict] = mapped_column(JSON)
    test_metrics: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class CapacitySnapshot(Base, TimestampMixin):
    __tablename__ = "capacity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_identifier: Mapped[str] = mapped_column("provider_code", String(16), index=True)
    snapshot_month: Mapped[date] = mapped_column(Date)
    beds_total: Mapped[int] = mapped_column(Integer)
    beds_occupied: Mapped[int] = mapped_column(Integer)
    staff_available: Mapped[float] = mapped_column(Float)
    staff_required: Mapped[float] = mapped_column(Float, default=0)
    equipment_available: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    data_origin: Mapped[str] = mapped_column(String(50), default="user-entered")


class SimulationRun(Base, TimestampMixin):
    __tablename__ = "simulation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_identifier: Mapped[str] = mapped_column("provider_code", String(16))
    scenario: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


class OptimisationPlan(Base, TimestampMixin):
    __tablename__ = "optimisation_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hospital_identifier: Mapped[str] = mapped_column("provider_code", String(16))
    input_data: Mapped[dict] = mapped_column(JSON)
    recommendation: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending_review")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class OperationsIntelligenceConversation(Base, TimestampMixin):
    __tablename__ = "operations_intelligence_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(300), default="Operational review")


class OperationsIntelligenceMessage(Base, TimestampMixin):
    __tablename__ = "operations_intelligence_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("operations_intelligence_conversations.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    structured_response: Mapped[dict | None] = mapped_column(JSON)


class OperationsIntelligenceToolCall(Base, TimestampMixin):
    __tablename__ = "operations_intelligence_tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("operations_intelligence_conversations.id"))
    tool_name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))


class PolicyDocument(Base, TimestampMixin):
    __tablename__ = "policy_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    checksum: Mapped[str] = mapped_column(String(64))
    text_content: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(500))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON)


class PolicyChunk(Base, TimestampMixin):
    __tablename__ = "policy_chunks"
    __table_args__ = (UniqueConstraint("document_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(150))


class AgentConversationScope(Base):
    __tablename__ = "agent_conversation_scopes"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("operations_intelligence_conversations.id"), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"))


class HospitalForecastHistory(Base, TimestampMixin):
    __tablename__ = "hospital_forecast_histories"
    forecast_id: Mapped[str] = mapped_column(ForeignKey("forecast_runs.id"), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(String(16), index=True)
    history: Mapped[list] = mapped_column(JSON)


class Hospital(Base, TimestampMixin):
    __tablename__ = "hospitals"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    data_origin: Mapped[str] = mapped_column(String(40), default="staff-entered")


class Ward(Base, TimestampMixin):
    __tablename__ = "wards"
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    floor: Mapped[str] = mapped_column(String(60))
    specialty: Mapped[str] = mapped_column(String(80))


class Bed(Base, TimestampMixin):
    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("ward_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id"), index=True)
    label: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="available")
    staffed: Mapped[bool] = mapped_column(Boolean, default=True)
    capability: Mapped[str] = mapped_column(String(120), default="General")
    note: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmergencySnapshot(Base, TimestampMixin):
    __tablename__ = "emergency_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    awaiting_assessment: Mapped[int] = mapped_column(Integer)
    awaiting_bed: Mapped[int] = mapped_column(Integer)
    high_priority: Mapped[int] = mapped_column(Integer)
    medium_priority: Mapped[int] = mapped_column(Integer)
    low_priority: Mapped[int] = mapped_column(Integer)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class ResourceRecord(Base, TimestampMixin):
    __tablename__ = "resource_records"
    __table_args__ = (UniqueConstraint("hospital_id", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    available_staff_hours: Mapped[float] = mapped_column(Float)
    equipment_available: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(String(500), default="")


class OperationalTask(Base, TimestampMixin):
    __tablename__ = "operational_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(20), default="routine")
    status: Mapped[str] = mapped_column(String(20), default="open")
    note: Mapped[str] = mapped_column(String(500), default="")


class StaffShift(Base, TimestampMixin):
    __tablename__ = "staff_shifts"
    __table_args__ = (UniqueConstraint("hospital_id", "shift_date", "shift", "team"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    shift_date: Mapped[date] = mapped_column(Date)
    shift: Mapped[str] = mapped_column(String(20))
    team: Mapped[str] = mapped_column(String(80))
    required_staff: Mapped[int] = mapped_column(Integer)
    available_staff: Mapped[int] = mapped_column(Integer)
    hours_per_person: Mapped[float] = mapped_column(Float)


class EquipmentStock(Base, TimestampMixin):
    __tablename__ = "equipment_stock"
    __table_args__ = (UniqueConstraint("hospital_id", "name", "location"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(100))
    total: Mapped[int] = mapped_column(Integer)
    available: Mapped[int] = mapped_column(Integer)
