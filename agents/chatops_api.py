"""HTTP API for ChatOps Webhook Gateway, dispatching, and interactive human-in-the-loop decisions."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.chatops_client import get_chatops_client
from agents.incident_api import ApprovalRequest, decide_incident

router = APIRouter(prefix="/chatops", tags=["chatops"])


class ChatOpsDispatchRequest(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    summary: str = Field(min_length=3, max_length=1000)
    event_type: Literal[
        "incident_alert",
        "approval_requested",
        "incident_resolved",
        "decision_recorded",
        "test_ping",
    ] = "incident_alert"
    incident_id: str | None = Field(default=None, max_length=120)
    severity: Literal["critical", "warning", "info", "success"] = "warning"
    fields: dict[str, Any] | None = None
    actionable: bool = False


class ChatOpsInteractiveRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=120)
    decision: Literal["approve", "reject"]
    reviewed_by: str = Field(default="chatops-engineer", min_length=1, max_length=100)


class ChatOpsConfigRequest(BaseModel):
    slack_url: str | None = None
    discord_url: str | None = None
    generic_url: str | None = None
    enabled: bool | None = None


@router.get("/status", summary="Get ChatOps webhook configuration and delivery stats")
def get_chatops_status() -> dict[str, Any]:
    """Return status of configured ChatOps platforms, masked URLs, and simulation state."""
    client = get_chatops_client()
    return client.get_status()


@router.get("/history", summary="Get recent dispatched ChatOps messages")
def get_chatops_history(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, Any]]:
    """Return in-memory ring buffer of recently dispatched Slack/Discord/Generic cards."""
    client = get_chatops_client()
    return client.get_history(limit=limit)


@router.post("/dispatch", summary="Dispatch a manual or custom ChatOps notification")
def dispatch_chatops_notification(request: ChatOpsDispatchRequest) -> dict[str, Any]:
    """Dispatch a custom notification or alert card across configured/simulated platforms."""
    client = get_chatops_client()
    result = client.dispatch(
        event_type=request.event_type,
        title=request.title,
        summary=request.summary,
        incident_id=request.incident_id,
        severity=request.severity,
        fields=request.fields,
        actionable=request.actionable,
    )
    return result


@router.post("/interactive", summary="Process inbound interactive human-in-the-loop decision from ChatOps")
def process_chatops_interaction(request: ChatOpsInteractiveRequest) -> dict[str, Any]:
    """Handle interactive button click (Approve/Reject) from Slack/Discord and resume workflow."""
    incident_id = request.incident_id.strip()
    reviewed_by = request.reviewed_by.strip() or "chatops-engineer"

    approval_req = ApprovalRequest(
        decision=request.decision,
        reviewed_by=reviewed_by,
    )

    try:
        updated_incident = decide_incident(incident_id, approval_req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"ChatOps approval execution failed: {exc}",
        ) from exc

    # Automatically announce the resolution back to ChatOps
    client = get_chatops_client()
    client.notify_decision_recorded(
        incident_id=incident_id,
        decision=request.decision,
        reviewed_by=reviewed_by,
        result=updated_incident,
    )

    return {
        "status": "success",
        "incident_id": incident_id,
        "decision": request.decision,
        "reviewed_by": reviewed_by,
        "incident": updated_incident,
    }


@router.post("/config", summary="Update webhook configuration dynamically")
def update_chatops_config(request: ChatOpsConfigRequest) -> dict[str, Any]:
    """Configure Slack, Discord, or generic webhook URLs and toggle enablement."""
    client = get_chatops_client()
    return client.configure(
        slack_url=request.slack_url,
        discord_url=request.discord_url,
        generic_url=request.generic_url,
        enabled=request.enabled,
    )


@router.post("/test", summary="Send a test notification card")
def send_chatops_test() -> dict[str, Any]:
    """Fire a test card across all configured or simulated channels."""
    client = get_chatops_client()
    return client.notify_test_ping(platform="all")

