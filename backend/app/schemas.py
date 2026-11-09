from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: str


class HospitalMonthInput(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    emergency_admissions: float = Field(ge=0)
    total_ae_attendances: float = Field(gt=0)
    attendances_under_4_hours: float = Field(ge=0)
    decision_to_admit_waits_over_4_hours: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "HospitalMonthInput":
        if self.attendances_under_4_hours > self.total_ae_attendances:
            raise ValueError("Attendances within four hours cannot exceed total attendances")
        if self.decision_to_admit_waits_over_4_hours > self.total_ae_attendances:
            raise ValueError("Decision-to-admit waits cannot exceed total attendances")
        return self


class HospitalForecastRequest(BaseModel):
    hospital_name: str = Field(min_length=2, max_length=300)
    hospital_identifier: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    history: list[HospitalMonthInput] = Field(min_length=13, max_length=120)

    @model_validator(mode="after")
    def validate_history(self) -> "HospitalForecastRequest":
        import pandas as pd

        periods = sorted(pd.Period(row.month, freq="M") for row in self.history)
        if len(periods) != len(set(periods)):
            raise ValueError("History contains duplicate months")
        expected = list(pd.period_range(periods[0], periods[-1], freq="M"))
        if periods != expected:
            raise ValueError("History must contain consecutive completed months without gaps")
        if periods[-1] >= pd.Period(date.today(), freq="M"):
            raise ValueError("History must end in a completed month before the current month")
        return self


class CapacityIn(BaseModel):
    hospital_identifier: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    snapshot_month: date
    staffed_beds: int = Field(ge=0)
    occupied_beds: int = Field(ge=0)
    available_staff_hours: float = Field(ge=0)
    required_staff_hours: float = Field(ge=0)
    equipment_available: int = Field(ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.occupied_beds > self.staffed_beds:
            raise ValueError("Occupied beds cannot exceed staffed beds")
        return self


class SimulationRequest(BaseModel):
    hospital_identifier: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    monthly_demand: float = Field(gt=0)
    staffed_beds: int = Field(gt=0)
    average_length_of_stay_hours: float = Field(default=30, gt=0)
    replications: int = Field(default=20, ge=1, le=500)
    seed: int = 42


class OptimisationRequest(BaseModel):
    hospital_identifier: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    required_bed_hours: float = Field(gt=0)
    available_bed_hours: float = Field(gt=0)
    required_staff_hours: float = Field(gt=0)
    available_staff_hours: float = Field(gt=0)
    max_extra_beds: int = Field(default=50, ge=0)
    max_extra_staff_hours: int = Field(default=1000, ge=0)


class ApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = None


class IntelligenceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    hospital_id: str = Field(min_length=2, max_length=16)
    allow_compute: bool = False


class PolicyIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=10, max_length=200000)
    source: str | None = Field(default=None, max_length=500)


class StatusResponse(BaseModel):
    status: str
    detail: dict[str, Any] = {}
    checked_at: datetime = Field(default_factory=datetime.utcnow)
