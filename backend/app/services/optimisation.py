from __future__ import annotations

from ortools.linear_solver import pywraplp


class OptimisationService:
    def solve(self, payload: dict) -> dict:
        solver = pywraplp.Solver.CreateSolver("SCIP")
        if solver is None:
            raise RuntimeError("OR-Tools solver is unavailable")
        beds = solver.IntVar(0, payload["max_extra_beds"], "extra_beds")
        staff = solver.IntVar(0, payload["max_extra_staff_hours"], "extra_staff_hours")
        solver.Add(payload["available_bed_hours"] + beds * payload.get("bed_hours_per_extra_bed", 24) >= payload["required_bed_hours"])
        solver.Add(payload["available_staff_hours"] + staff >= payload["required_staff_hours"])
        solver.Minimize(beds * payload.get("extra_bed_cost", 500) + staff * 45)
        status = solver.Solve()
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return {"status": "infeasible", "recommendation": {}}
        return {
            "status": "pending_approval",
            "recommendation": {
                "extra_beds": int(beds.solution_value()),
                "extra_staff_hours": int(staff.solution_value()),
                "estimated_incremental_cost": round(solver.Objective().Value(), 2),
            },
            "guardrail": "This plan is advisory and cannot be applied without human approval.",
        }
