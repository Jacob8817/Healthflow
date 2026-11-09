from __future__ import annotations

import math

import numpy as np
import simpy


class SimulationService:
    """Deterministic, seeded patient-flow simulation."""

    def run(
        self,
        *,
        monthly_demand: float,
        staffed_beds: int,
        average_length_of_stay_hours: float,
        replications: int,
        seed: int,
        horizon_days: int = 30,
    ) -> dict:
        horizon = horizon_days * 24
        outcomes: list[dict] = []
        for replication in range(replications):
            rng = np.random.default_rng(seed + replication)
            env = simpy.Environment()
            beds = simpy.Resource(env, capacity=staffed_beds)
            waits: list[float] = []
            occupancies: list[float] = []
            occupied_hours = 0.0

            def patient():
                nonlocal occupied_hours
                arrived = env.now
                with beds.request() as request:
                    yield request
                    waits.append(env.now - arrived)
                    occupancies.append(beds.count / staffed_beds)
                    stay = rng.exponential(average_length_of_stay_hours)
                    occupied_hours += min(stay, horizon - env.now)
                    yield env.timeout(stay)

            def arrivals():
                hourly_rate = monthly_demand / horizon
                while env.now < horizon:
                    yield env.timeout(rng.exponential(1 / hourly_rate))
                    env.process(patient())

            env.process(arrivals())
            env.run(until=horizon)
            outcomes.append(
                {
                    "mean_wait_hours": float(np.mean(waits)) if waits else 0,
                    "p95_wait_hours": float(np.quantile(waits, 0.95)) if waits else 0,
                    "mean_occupancy": occupied_hours / (staffed_beds * horizon),
                    "waiting_at_end": len(beds.queue),
                    "patients_started": len(waits),
                }
            )
        keys = outcomes[0].keys()
        summary = {key: float(np.mean([row[key] for row in outcomes])) for key in keys}
        summary["replications"] = replications
        summary["seed"] = seed
        summary["monthly_to_hourly_rate"] = monthly_demand / horizon
        summary["capacity_risk"] = (
            "high" if summary["mean_occupancy"] >= 0.9 or summary["p95_wait_hours"] >= 4 else "moderate"
            if summary["mean_occupancy"] >= 0.8 else "low"
        )
        return summary
