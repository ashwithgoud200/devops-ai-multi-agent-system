"""HTTP API for the interruptible, human-approved incident workflow."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field

from agents import graph, llm_runtime

ROOT = Path(__file__).resolve().parents[1]
AUDIT_LOG_PATH = ROOT / "logs" / "incident_audit.jsonl"
_AUDIT_LOCK = threading.Lock()
_WORKFLOW = graph.build()
router = APIRouter(tags=["incident workflow"])


class IncidentRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)


class ApprovalRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewed_by: str = Field(min_length=1, max_length=120)


def _config(incident_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": incident_id}}


def _audit_path() -> Path:
    return Path(os.getenv("DEVOPS_AUDIT_LOG_PATH", str(AUDIT_LOG_PATH)))


def _append_audit(
    event: str,
    incident_id: str,
    **details: Any,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "incident_id": incident_id,
        **details,
    }
    path = _audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK, path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist the incident audit record.",
        ) from exc


def _read_audit(incident_id: str) -> list[dict[str, Any]]:
    return _read_audit_events(incident_id)


def _read_audit_events(incident_id: str | None = None) -> list[dict[str, Any]]:
    path = _audit_path()
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"Audit line {line_number} is not an object")
                if incident_id is None or record.get("incident_id") == incident_id:
                    records.append(record)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="The incident audit log could not be read.",
        ) from exc
    return records


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return llm_runtime._redact_sensitive_content(value)
    return value


def _snapshot(incident_id: str):
    snapshot = _WORKFLOW.get_state(_config(incident_id))
    if not isinstance(snapshot.values, dict) or not snapshot.values:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return snapshot


def _approval_request(snapshot: Any) -> dict[str, Any] | None:
    for task in getattr(snapshot, "tasks", ()):
        for interrupted in getattr(task, "interrupts", ()):
            value = getattr(interrupted, "value", None)
            if isinstance(value, dict):
                return value
    return None


def _incident_response(incident_id: str, snapshot: Any) -> dict[str, Any]:
    values = snapshot.values
    approval = _approval_request(snapshot)
    if approval is not None or "request_approval" in snapshot.next:
        status = "pending_approval"
    elif isinstance(values.get("report"), dict):
        status = "completed"
    else:
        status = "running"
    return _redact({
        "incident_id": incident_id,
        "status": status,
        "query": values.get("query"),
        "trace": values.get("trace", []),
        "evidence": values.get("evidence"),
        "baseline_comparison": values.get("comparison"),
        "specialists": values.get("specialists"),
        "diagnosis": values.get("diagnosis"),
        "proposed_remediation": values.get("remediation"),
        "approval_request": approval,
        "outcome": values.get("outcome"),
        "report": values.get("report"),
    })


def _run(
    config: RunnableConfig,
    input_value: graph.IncidentState | Command[Any],
) -> None:
    for _ in _WORKFLOW.stream(input_value, config, stream_mode="updates"):
        pass


@router.post("/baseline", summary="Collect and save a telemetry baseline")
def create_baseline() -> dict[str, Any]:
    snapshot = graph.save_baseline()
    _append_audit(
        "baseline_saved",
        str(uuid.uuid4()),
        status="saved",
        telemetry_availability=graph._telemetry_availability(snapshot),
    )
    return _redact({"status": "saved", "snapshot": snapshot})


@router.get("/agents", summary="Read configured specialist agents")
def read_agents() -> dict[str, Any]:
    config = llm_runtime.load_config()
    agents = config.get("agents", {})
    return {
        "enabled": bool(config.get("enabled", False)),
        "agents": [
            {
                "id": agent_id,
                "model": details.get("model"),
                "role": details.get("role"),
            }
            for agent_id, details in agents.items()
            if isinstance(details, dict)
        ],
    }


@router.get("/baseline", summary="Read the saved baseline")
def read_baseline() -> dict[str, Any]:
    return _redact(graph._load_baseline())


@router.post("/incidents", summary="Collect evidence and diagnose an incident")
def start_incident(request: IncidentRequest) -> dict[str, Any]:
    query = request.query.strip()
    if len(query) < 3:
        raise HTTPException(status_code=422, detail="query must contain at least 3 non-space characters.")
    incident_id = str(uuid.uuid4())
    config = _config(incident_id)
    _append_audit("incident_started", incident_id)
    initial_state: graph.IncidentState = {"query": query, "trace": []}
    _run(config, initial_state)
    snapshot = _snapshot(incident_id)
    response = _incident_response(incident_id, snapshot)
    _append_audit(
        "diagnosis_finished",
        incident_id,
        status=response["status"],
        remediation_action=(response.get("proposed_remediation") or {}).get("action"),
    )
    return response


@router.get("/incidents/{incident_id}", summary="Read diagnosis, evidence and action status")
def read_incident(incident_id: str) -> dict[str, Any]:
    return _incident_response(incident_id, _snapshot(incident_id))


@router.post(
    "/incidents/{incident_id}/approval",
    summary="Approve or reject a proposed action",
)
def decide_incident(
    incident_id: str,
    request: ApprovalRequest,
) -> dict[str, Any]:
    snapshot = _snapshot(incident_id)
    approval = _approval_request(snapshot)
    if approval is None:
        raise HTTPException(
            status_code=409,
            detail="This incident has no action awaiting human approval.",
        )
    reviewed_by = request.reviewed_by.strip()
    if not reviewed_by:
        raise HTTPException(status_code=422, detail="reviewed_by cannot be blank.")
    approved = request.decision == "approve"
    _append_audit(
        "approval_decision",
        incident_id,
        decision=request.decision,
        reviewed_by=reviewed_by,
        action=approval.get("action"),
        target_version=approval.get("target_version"),
    )
    _run(_config(incident_id), Command(resume=approved))
    result = _incident_response(incident_id, _snapshot(incident_id))
    _append_audit(
        "action_finished",
        incident_id,
        decision=request.decision,
        reviewed_by=reviewed_by,
        outcome_status=(result.get("outcome") or {}).get("status"),
    )
    return result


@router.get("/incidents/{incident_id}/audit", summary="Read incident audit events")
def read_incident_audit(incident_id: str) -> dict[str, Any]:
    _snapshot(incident_id)
    return {"incident_id": incident_id, "events": _read_audit(incident_id)}


@router.get("/audit", summary="Read all incident audit events")
def read_audit() -> dict[str, Any]:
    return {"events": _read_audit_events()}
