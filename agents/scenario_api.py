"""HTTP API for synthetic scenario management and fault injection."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents import scenarios
from agents.incident_api import _append_audit
from agents import remote_app_client

logger = logging.getLogger("scenario_api")
router = APIRouter(prefix="/scenarios", tags=["synthetic scenarios"])


class ScenarioActionResponse(BaseModel):
    scenario_id: str
    status: str
    message: str
    activated_at: float | None = None
    reset_at: float | None = None
    faults: dict[str, Any] = Field(default_factory=dict)


@router.get("", summary="List all five synthetic incident scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    """Return all supported synthetic scenarios with status and verification details."""
    return scenarios.get_all_scenarios()


@router.get("/status", summary="Get current scenario and fault injection status")
def scenario_status() -> dict[str, Any]:
    """Return currently active scenario, active faults, and activation timestamp."""
    return scenarios.get_scenario_status()


@router.get("/{scenario_id}", summary="Get details of a specific synthetic scenario")
def get_scenario_details(scenario_id: str) -> dict[str, Any]:
    """Return scenario definition, expected symptoms, and verification instructions."""
    defn = scenarios.get_scenario(scenario_id)
    if defn is None:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario_id}' not found. Supported: {list(scenarios.ALL_SCENARIOS)}",
        )
    return defn


@router.post("/{scenario_id}/activate", summary="Activate a synthetic incident scenario")
def activate_scenario_endpoint(scenario_id: str) -> dict[str, Any]:
    """Activate synthetic fault injection for the specified scenario."""
    from calculator_app import app as calc_app

    try:
        result = scenarios.activate_scenario(
            scenario_id=scenario_id,
            calculator_state=calc_app.STATE,
            log_func=calc_app.log,
        )

        # Synchronize fault injection with deployed/remote app
        sid = scenario_id.strip().upper()
        if sid in ("DEPLOYMENT_REGRESSION", "GENERAL_INCIDENT"):
            remote_app_client.remote_deploy(version="1.1", bug=True)
            if sid == "GENERAL_INCIDENT":
                remote_app_client.remote_inject_latency(0.25)
        elif sid == "PERFORMANCE_DRIFT":
            remote_app_client.remote_inject_latency(0.45)
            remote_app_client.remote_stress_cpu(duration_seconds=30, num_threads=2)
        elif sid == "INFRASTRUCTURE_FAILURE":
            remote_app_client.remote_stress_memory(megabytes=150, duration_seconds=30)
            remote_app_client.remote_stress_cpu(duration_seconds=30, num_threads=1)

        _append_audit(
            event="scenario_activated",
            incident_id=f"scenario-{scenario_id.lower()}",
            scenario_id=scenario_id.upper(),
            faults=result.get("faults"),
        )
        return {
            "scenario_id": result["scenario_id"],
            "active_scenario": result["scenario_id"],
            "status": "active",
            "message": f"Scenario {scenario_id} activated successfully. Faults injected.",
            "activated_at": result["activated_at"],
            "faults": result["faults"],
            "definition": result["definition"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{scenario_id}/reset", summary="Reset a synthetic scenario and clear faults")
def reset_scenario_endpoint(scenario_id: str) -> dict[str, Any]:
    """Reset faults and return application state to clean v1.0 baseline."""
    from calculator_app import app as calc_app

    result = scenarios.reset_scenario(
        scenario_id=scenario_id,
        calculator_state=calc_app.STATE,
        log_func=calc_app.log,
    )

    # Synchronize reset with deployed/remote app
    remote_app_client.remote_reset_faults()
    remote_app_client.remote_rollback()

    _append_audit(
        event="scenario_reset",
        incident_id=f"scenario-{scenario_id.lower()}",
        scenario_id=scenario_id.upper(),
    )
    return {
        "scenario_id": result["scenario_id"],
        "active_scenario": None,
        "status": "reset",
        "message": f"Scenario {scenario_id} reset successfully. All faults cleared.",
        "reset_at": result["reset_at"],
        "faults": result["faults"],
    }
