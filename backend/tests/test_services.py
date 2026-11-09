from app.services.optimisation import OptimisationService
from app.services.simulation import SimulationService


def test_simulation_is_deterministic():
    args = dict(monthly_demand=300, staffed_beds=20, average_length_of_stay_hours=10,
                replications=2, seed=7)
    service = SimulationService()
    assert service.run(**args) == service.run(**args)


def test_optimisation_requires_enough_resources():
    result = OptimisationService().solve({
        "required_bed_hours": 1000, "available_bed_hours": 900,
        "required_staff_hours": 500, "available_staff_hours": 450,
        "max_extra_beds": 10, "max_extra_staff_hours": 100,
    })
    assert result["status"] == "pending_approval"
    assert result["recommendation"]["extra_beds"] >= 5
    assert result["recommendation"]["extra_staff_hours"] >= 50
