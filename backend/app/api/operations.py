"""Staff-maintained operational state and forecast-linked scenario planning."""
from __future__ import annotations

import calendar
import math
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.core.config import get_settings
from app.db.models import (AuditLog, Bed, EmergencySnapshot, EquipmentStock, ForecastRun, Hospital,
                           OperationalTask, OptimisationPlan, ResourceRecord,
                           SimulationRun, StaffShift, User, Ward)

router = APIRouter(prefix="/operations", tags=["Staff operations"])
write_access = require_roles("admin", "planner")
Code = str
BedState = Literal["available", "occupied", "reserved", "cleaning", "blocked"]


class HospitalIn(BaseModel):
    id: str = Field(pattern=r"^[A-Z0-9_-]{2,16}$")
    name: str = Field(min_length=2, max_length=200)


class WardIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    floor: str = Field(min_length=1, max_length=60)
    specialty: str = Field(min_length=2, max_length=80)
    bed_count: int = Field(ge=1, le=200)
    capability: str = Field(default="General", min_length=1, max_length=120)


class BedUpdate(BaseModel):
    status: BedState
    staffed: bool
    note: str = Field(default="", max_length=500)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def valid(self):
        if self.status == "available" and not self.staffed:
            raise ValueError("An available bed must be staffed. Use blocked for an unstaffed bed.")
        return self


class EmergencyIn(BaseModel):
    awaiting_assessment: int = Field(ge=0, le=10000)
    awaiting_bed: int = Field(ge=0, le=10000)
    high_priority: int = Field(ge=0, le=10000)
    medium_priority: int = Field(ge=0, le=10000)
    low_priority: int = Field(ge=0, le=10000)


class ResourceIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    available_staff_hours: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    equipment_available: int = Field(ge=0, le=100000)
    notes: str = Field(default="", max_length=500)


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    owner: str = Field(min_length=2, max_length=100)
    priority: Literal["routine", "urgent"] = "routine"
    note: str = Field(default="", max_length=500)


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "done"]


class ShiftIn(BaseModel):
    shift_date: date
    shift: Literal["Day", "Evening", "Night"]
    team: str = Field(min_length=2, max_length=80)
    required_staff: int = Field(ge=0, le=10000)
    available_staff: int = Field(ge=0, le=10000)
    hours_per_person: float = Field(gt=0, le=24, allow_inf_nan=False)


class EquipmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    location: str = Field(min_length=2, max_length=100)
    total: int = Field(ge=0, le=100000)
    available: int = Field(ge=0, le=100000)

    @model_validator(mode="after")
    def valid_counts(self):
        if self.available > self.total:
            raise ValueError("Available equipment cannot exceed total units")
        return self


class PlanningIn(BaseModel):
    forecast_id: str
    average_length_of_stay_hours: float = Field(default=20, gt=0, le=720, allow_inf_nan=False)
    target_occupancy: float = Field(default=0.85, ge=0.5, le=1, allow_inf_nan=False)
    staff_hours_per_admission: float = Field(default=4, gt=0, le=200, allow_inf_nan=False)
    max_extra_beds: int = Field(default=100, ge=0, le=1000)
    max_extra_staff_hours: int = Field(default=10000, ge=0, le=1000000)


def hospital_or_404(db, hospital_id):
    row = db.get(Hospital, hospital_id)
    if not row:
        raise HTTPException(404, "Hospital not found")
    return row


def audit(db, user, action, details):
    db.add(AuditLog(actor_id=user.id, action=action, details=details))


def inventory(db, hospital_id):
    wards = db.scalars(select(Ward).where(Ward.hospital_id == hospital_id).order_by(Ward.id)).all()
    beds = db.scalars(select(Bed).join(Ward).where(Ward.hospital_id == hospital_id).order_by(Bed.id)).all()
    counts = {s: sum(b.status == s for b in beds) for s in ("available", "occupied", "reserved", "cleaning", "blocked")}
    return wards, beds, {**counts, "total": len(beds),
        "staffed_operational": sum(b.staffed and b.status != "blocked" for b in beds),
        "available": sum(b.staffed and b.status == "available" for b in beds)}


@router.get("/hospitals")
def hospitals(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Hospital).order_by(Hospital.name)).all()


@router.post("/hospitals", status_code=201)
def add_hospital(payload: HospitalIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    if db.get(Hospital, payload.id):
        raise HTTPException(409, "Hospital identifier already exists")
    row = Hospital(**payload.model_dump())
    db.add(row)
    audit(db, user, "hospital.created", {"hospital_id": payload.id})
    db.commit()
    return row


@router.post("/demo")
def demo(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    if get_settings().app_env != "development":
        raise HTTPException(403, "Demonstration data is available only in development")
    code = "DEMO-HOSP-01"
    if db.get(Hospital, code):
        return {"hospital_id": code}
    db.add(Hospital(id=code, name="City General Hospital", data_origin="demonstration"))
    db.flush()
    for name, floor, specialty, counts, capability in [
        ("Emergency department", "Ground floor", "Emergency", [18, 2, 2, 1, 1], "Monitored bay"),
        ("Intensive care", "Ground floor", "Critical care", [9, 1, 0, 1, 1], "Ventilator capable"),
        ("Medical ward", "First floor", "General medicine", [36, 8, 2, 1, 1], "General"),
        ("Surgical ward", "First floor", "Surgery", [27, 5, 2, 1, 1], "Post-operative"),
    ]:
        ward = Ward(hospital_id=code, name=name, floor=floor, specialty=specialty)
        db.add(ward); db.flush()
        statuses = [state for state, n in zip(["occupied", "available", "cleaning", "reserved", "blocked"], counts) for _ in range(n)]
        for i, state in enumerate(statuses):
            db.add(Bed(ward_id=ward.id, label=f"{i+1:02d}", status=state, staffed=state != "blocked", capability=capability,
                       note="Synthetic demonstration record"))
    db.add(EmergencySnapshot(hospital_id=code, awaiting_assessment=5, awaiting_bed=7, high_priority=4,
                            medium_priority=11, low_priority=8, recorded_by=user.id))
    db.add(ResourceRecord(hospital_id=code, month="2026-08", available_staff_hours=15000,
                          equipment_available=24, notes="Demonstration monthly staffing budget; 24 available monitors."))
    for title, owner, priority in [("Confirm bed cleaning completion", "Housekeeping lead", "urgent"),
                                   ("Review blocked capacity", "Bed management", "urgent"),
                                   ("Confirm next-month staff coverage", "Rostering team", "routine")]:
        db.add(OperationalTask(hospital_id=code, title=title, owner=owner, priority=priority, note="Demonstration task"))
    audit(db, user, "demo.created", {"hospital_id": code})
    db.commit()
    return {"hospital_id": code}


@router.get("/{hospital_id}/board")
def board(hospital_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    hospital = hospital_or_404(db, hospital_id)
    wards, beds, counts = inventory(db, hospital_id)
    emergency = db.scalar(select(EmergencySnapshot).where(EmergencySnapshot.hospital_id == hospital_id).order_by(EmergencySnapshot.id.desc()))
    forecasts = db.scalars(select(ForecastRun).where(ForecastRun.hospital_identifier == hospital_id).order_by(ForecastRun.created_at.desc()).limit(30)).all()
    return {"hospital": hospital, "wards": wards, "beds": beds, "counts": counts, "emergency": emergency,
            "forecasts": forecasts,
            "resources": db.scalars(select(ResourceRecord).where(ResourceRecord.hospital_id == hospital_id).order_by(ResourceRecord.month.desc())).all(),
            "tasks": db.scalars(select(OperationalTask).where(OperationalTask.hospital_id == hospital_id).order_by(OperationalTask.id)).all(),
            "shifts": db.scalars(select(StaffShift).where(StaffShift.hospital_id == hospital_id).order_by(StaffShift.shift_date.desc(), StaffShift.id).limit(500)).all(),
            "equipment": db.scalars(select(EquipmentStock).where(EquipmentStock.hospital_id == hospital_id).order_by(EquipmentStock.id)).all(),
            "plans": db.scalars(select(OptimisationPlan).where(OptimisationPlan.hospital_identifier == hospital_id).order_by(OptimisationPlan.created_at.desc()).limit(20)).all()}


@router.post("/{hospital_id}/wards", status_code=201)
def add_ward(hospital_id: str, payload: WardIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    ward = Ward(hospital_id=hospital_id, **payload.model_dump(exclude={"bed_count", "capability"}))
    db.add(ward); db.flush()
    for i in range(payload.bed_count):
        db.add(Bed(ward_id=ward.id, label=f"{i+1:02d}", status="blocked", staffed=False, capability=payload.capability, note="Confirm staffing before opening"))
    audit(db, user, "ward.created", {"hospital_id": hospital_id, "ward_id": ward.id, "beds": payload.bed_count})
    db.commit()
    return ward


@router.patch("/{hospital_id}/beds/{bed_id}")
def update_bed(hospital_id: str, bed_id: int, payload: BedUpdate, db: Session = Depends(get_db), user: User = Depends(write_access)):
    bed = db.scalar(select(Bed).join(Ward).where(Bed.id == bed_id, Ward.hospital_id == hospital_id))
    if not bed:
        raise HTTPException(404, "Bed not found in this hospital")
    before = {"status": bed.status, "staffed": bed.staffed, "version": bed.version}
    result = db.execute(update(Bed).where(Bed.id == bed_id, Bed.version == payload.version)
        .values(**payload.model_dump(exclude={"version"}), version=payload.version + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This bed was updated by another user. Refresh before saving.")
    audit(db, user, "bed.updated", {"bed_id": bed_id, "hospital_id": hospital_id, "before": before, "after": payload.model_dump()})
    db.commit(); db.refresh(bed)
    return bed


@router.post("/{hospital_id}/emergency")
def save_emergency(hospital_id: str, payload: EmergencyIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    row = EmergencySnapshot(hospital_id=hospital_id, recorded_by=user.id, **payload.model_dump())
    db.add(row); audit(db, user, "emergency.recorded", {"hospital_id": hospital_id, **payload.model_dump()})
    db.commit()
    return row


@router.put("/{hospital_id}/resources")
def save_resources(hospital_id: str, payload: ResourceIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    row = db.scalar(select(ResourceRecord).where(ResourceRecord.hospital_id == hospital_id, ResourceRecord.month == payload.month))
    if row is None:
        row = ResourceRecord(hospital_id=hospital_id, **payload.model_dump()); db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    audit(db, user, "resources.recorded", {"hospital_id": hospital_id, **payload.model_dump()})
    db.commit()
    return row


@router.post("/{hospital_id}/tasks", status_code=201)
def add_task(hospital_id: str, payload: TaskIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    row = OperationalTask(hospital_id=hospital_id, **payload.model_dump()); db.add(row)
    audit(db, user, "task.created", {"hospital_id": hospital_id, **payload.model_dump()})
    db.commit()
    return row


@router.patch("/{hospital_id}/tasks/{task_id}")
def update_task(hospital_id: str, task_id: int, payload: TaskUpdate, db: Session = Depends(get_db), user: User = Depends(write_access)):
    row = db.get(OperationalTask, task_id)
    if not row or row.hospital_id != hospital_id:
        raise HTTPException(404, "Task not found")
    row.status = payload.status
    audit(db, user, "task.updated", {"hospital_id": hospital_id, "task_id": task_id, "status": payload.status})
    db.commit()
    return row


@router.post("/{hospital_id}/planning")
def plan(hospital_id: str, payload: PlanningIn, request: Request, db: Session = Depends(get_db), user: User = Depends(write_access)):
    return calculate_plan(hospital_id, payload, request, db, user, persist=True)


def calculate_plan(hospital_id, payload, request, db, user, *, persist=False):
    hospital_or_404(db, hospital_id)
    forecast = db.get(ForecastRun, payload.forecast_id)
    if not forecast or forecast.hospital_identifier != hospital_id:
        raise HTTPException(422, "Select a forecast for this hospital")
    _, beds, counts = inventory(db, hospital_id)
    available_beds = counts["staffed_operational"]
    if not available_beds:
        raise HTTPException(422, "Add staffed, non-blocked beds before planning")
    if forecast.displayed_prediction <= 0:
        raise HTTPException(422, "A positive demand forecast is required for this simulation")
    resource = db.scalar(select(ResourceRecord).where(ResourceRecord.hospital_id == hospital_id, ResourceRecord.month == forecast.target_month))
    if resource is None:
        raise HTTPException(422, f"Save staffing resources for {forecast.target_month} before planning")
    year, month = map(int, forecast.target_month.split("-"))
    days = calendar.monthrange(year, month)[1]
    hours = days * 24
    demand = forecast.displayed_prediction
    required_bed_hours = demand * payload.average_length_of_stay_hours / payload.target_occupancy
    required_staff_hours = demand * payload.staff_hours_per_admission
    solver_input = {"required_bed_hours": required_bed_hours, "available_bed_hours": available_beds * hours,
                    "required_staff_hours": required_staff_hours, "available_staff_hours": resource.available_staff_hours,
                    "max_extra_beds": payload.max_extra_beds, "max_extra_staff_hours": payload.max_extra_staff_hours,
                    "bed_hours_per_extra_bed": hours, "extra_bed_cost": days * 500}
    simulation_args = dict(monthly_demand=demand, staffed_beds=available_beds,
        average_length_of_stay_hours=payload.average_length_of_stay_hours, replications=20, seed=42, horizon_days=days)
    simulation = request.app.state.simulation_service.run(**simulation_args)
    result = request.app.state.optimisation_service.solve(solver_input)
    assumptions = {**payload.model_dump(), "target_month": forecast.target_month, "demand": demand,
                   "staffed_beds": available_beds, "resource_id": resource.id,
                   "resource_updated_at": resource.updated_at.isoformat(), "available_staff_hours": resource.available_staff_hours,
                   "inventory_updated_at": max(b.updated_at for b in beds).isoformat(), "horizon_days": days,
                   "cost_per_bed_day": 500, "cost_per_staff_hour": 45,
                   "scope": "Aggregate scenario; current inventory, not historical occupancy or live patient allocation."}
    result["simulation"] = simulation
    result["summary"] = {"required_beds_at_target": math.ceil(required_bed_hours / hours),
                         "bed_gap": max(0, math.ceil(required_bed_hours / hours) - available_beds),
                         "staff_hour_gap": max(0, math.ceil(required_staff_hours - resource.available_staff_hours)),
                         "offered_load_percent": round(demand * payload.average_length_of_stay_hours / (available_beds * hours) * 100, 1)}
    if not persist:
        return {"input_data": assumptions, "recommendation": result, "saved": False, "scope": "Preview only; no allocation or approval performed."}
    row = OptimisationPlan(id=str(uuid.uuid4()), hospital_identifier=hospital_id, input_data=assumptions, recommendation=result, status=result["status"])
    db.add(row)
    db.add(SimulationRun(id=str(uuid.uuid4()), hospital_identifier=hospital_id, scenario={**simulation_args, "forecast_id": forecast.id}, result=simulation))
    audit(db, user, "planning.generated", {"hospital_id": hospital_id, "plan_id": row.id, "forecast_id": forecast.id})
    db.commit()
    return row


@router.put("/{hospital_id}/shifts")
def save_shift(hospital_id: str, payload: ShiftIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    row = db.scalar(select(StaffShift).where(StaffShift.hospital_id == hospital_id,
        StaffShift.shift_date == payload.shift_date, StaffShift.shift == payload.shift, StaffShift.team == payload.team))
    if row is None:
        row = StaffShift(hospital_id=hospital_id, **payload.model_dump()); db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    audit(db, user, "shift.recorded", {"hospital_id": hospital_id, **payload.model_dump(mode="json")})
    db.commit()
    return row


@router.put("/{hospital_id}/equipment")
def save_equipment(hospital_id: str, payload: EquipmentIn, db: Session = Depends(get_db), user: User = Depends(write_access)):
    hospital_or_404(db, hospital_id)
    row = db.scalar(select(EquipmentStock).where(EquipmentStock.hospital_id == hospital_id,
        EquipmentStock.name == payload.name, EquipmentStock.location == payload.location))
    if row is None:
        row = EquipmentStock(hospital_id=hospital_id, **payload.model_dump()); db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    audit(db, user, "equipment.recorded", {"hospital_id": hospital_id, **payload.model_dump()})
    db.commit()
    return row
