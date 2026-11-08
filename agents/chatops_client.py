"""ChatOps & Webhook Gateway for OpsPilot Multi-Agent DevOps System.

Provides bidirectional ChatOps notifications and interactive human-in-the-loop
approvals for Slack, Discord, and generic HTTP webhooks.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import metrics as app_metrics

logger = logging.getLogger("chatops")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHATOPS_LOG_PATH = ROOT / "logs" / "chatops.jsonl"
_CHATOPS_LOCK = threading.Lock()

ALLOWED_PLATFORMS = ("slack", "discord", "generic", "all")
ALLOWED_EVENTS = (
    "incident_alert",
    "approval_requested",
    "incident_resolved",
    "decision_recorded",
    "test_ping",
    "other",
)
ALLOWED_STATUSES = ("delivered", "simulated", "failed", "disabled")


def _get_log_path() -> Path:
    return Path(os.getenv("DEVOPS_CHATOPS_LOG_PATH", str(DEFAULT_CHATOPS_LOG_PATH)))


class ChatOpsClient:
    """Manages multi-platform ChatOps notifications and interactive action handling."""

    _instance: ChatOpsClient | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> ChatOpsClient:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_client()
            return cls._instance

    def _init_client(self) -> None:
        self.lock = threading.RLock()
        self.history: collections.deque[dict[str, Any]] = collections.deque(maxlen=100)
        self.slack_webhook_url = os.getenv("CHATOPS_SLACK_WEBHOOK_URL", "").strip()
        self.discord_webhook_url = os.getenv("CHATOPS_DISCORD_WEBHOOK_URL", "").strip()
        self.generic_webhook_url = os.getenv("CHATOPS_GENERIC_WEBHOOK_URL", "").strip()
        self.enabled = os.getenv("CHATOPS_ENABLED", "true").lower() in ("1", "true", "yes")

    def configure(
        self,
        slack_url: str | None = None,
        discord_url: str | None = None,
        generic_url: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Update webhook endpoints and activation state dynamically."""
        with self.lock:
            if slack_url is not None:
                self.slack_webhook_url = slack_url.strip()
            if discord_url is not None:
                self.discord_webhook_url = discord_url.strip()
            if generic_url is not None:
                self.generic_webhook_url = generic_url.strip()
            if enabled is not None:
                self.enabled = bool(enabled)
            return self.get_status()

    def get_status(self) -> dict[str, Any]:
        """Return connectivity, configuration, and simulation status."""
        with self.lock:
            has_slack = bool(self.slack_webhook_url)
            has_discord = bool(self.discord_webhook_url)
            has_generic = bool(self.generic_webhook_url)
            has_any = has_slack or has_discord or has_generic

            return {
                "enabled": self.enabled,
                "simulation_mode": not has_any,
                "platforms": {
                    "slack": {
                        "configured": has_slack,
                        "masked_url": self._mask_url(self.slack_webhook_url),
                    },
                    "discord": {
                        "configured": has_discord,
                        "masked_url": self._mask_url(self.discord_webhook_url),
                    },
                    "generic": {
                        "configured": has_generic,
                        "masked_url": self._mask_url(self.generic_webhook_url),
                    },
                },
                "total_dispatched": len(self.history),
                "log_path": str(_get_log_path()),
            }

    @staticmethod
    def _mask_url(url: str) -> str:
        if not url:
            return ""
        if len(url) <= 18:
            return "******"
        return url[:12] + "..." + url[-6:]

    def build_slack_payload(
        self,
        event_type: str,
        title: str,
        summary: str,
        incident_id: str | None = None,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
        actionable: bool = False,
    ) -> dict[str, Any]:
        """Format a rich Slack Block Kit message payload."""
        emoji = {
            "incident_alert": "🚨",
            "approval_requested": "⚖️",
            "incident_resolved": "✅",
            "decision_recorded": "📝",
            "test_ping": "🔔",
        }.get(event_type, "ℹ️")

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{summary}*",
                },
            },
        ]

        # Detailed Key-Value fields
        detail_fields: list[dict[str, str]] = []
        if incident_id:
            detail_fields.append({"type": "mrkdwn", "text": f"*Incident ID:*\n`{incident_id[:12]}`"})
        detail_fields.append({"type": "mrkdwn", "text": f"*Severity:*\n*{severity.upper()}*"})

        if fields:
            for k, v in fields.items():
                if v:
                    clean_k = k.replace("_", " ").title()
                    detail_fields.append({"type": "mrkdwn", "text": f"*{clean_k}:*\n{v}"})

        if detail_fields:
            # Slack sections allow up to 10 fields
            blocks.append({
                "type": "section",
                "fields": detail_fields[:10],
            })

        # Add interactive buttons if awaiting human approval
        if actionable and incident_id:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "actions",
                "block_id": f"incident_approval_{incident_id[:8]}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve Remediation", "emoji": True},
                        "style": "primary",
                        "value": json.dumps({"incident_id": incident_id, "action": "approve"}),
                        "action_id": "chatops_approve_button",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject Remediation", "emoji": True},
                        "style": "danger",
                        "value": json.dumps({"incident_id": incident_id, "action": "reject"}),
                        "action_id": "chatops_reject_button",
                    },
                ],
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"OpsPilot Multi-Agent System · Environment: Local Loopback · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                }
            ],
        })

        return {"text": f"{emoji} {title}: {summary}", "blocks": blocks}

    def build_discord_payload(
        self,
        event_type: str,
        title: str,
        summary: str,
        incident_id: str | None = None,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
        actionable: bool = False,
    ) -> dict[str, Any]:
        """Format a rich Discord webhook embed payload."""
        # Embed colors: Red, Amber, Green, Blue
        color_map = {
            "critical": 0xDC2626,  # red-600
            "warning": 0xD97706,   # amber-600
            "info": 0x2563EB,      # blue-600
            "success": 0x059669,   # emerald-600
        }
        color = color_map.get(severity.lower(), 0x4B5563)
        if event_type == "incident_resolved":
            color = 0x059669
        elif event_type == "approval_requested":
            color = 0xD97706

        embed_fields: list[dict[str, Any]] = []
        if incident_id:
            embed_fields.append({"name": "Incident ID", "value": f"`{incident_id[:12]}`", "inline": True})
        embed_fields.append({"name": "Severity", "value": severity.upper(), "inline": True})

        if fields:
            for k, v in fields.items():
                if v:
                    clean_k = k.replace("_", " ").title()
                    embed_fields.append({"name": clean_k, "value": str(v)[:250], "inline": len(str(v)) < 40})

        if actionable and incident_id:
            embed_fields.append({
                "name": "Human-in-the-Loop Gate",
                "value": "Action pending human sign-off. Use OpsPilot UI or ChatOps callback API to Approve/Reject.",
                "inline": False,
            })

        embed = {
            "title": title,
            "description": summary,
            "color": color,
            "fields": embed_fields,
            "footer": {
                "text": "OpsPilot Multi-Agent System · Loopback 127.0.0.1",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "username": "OpsPilot Agent Bot",
            "content": f"**[ChatOps Alert]** {title}",
            "embeds": [embed],
        }

    def build_generic_payload(
        self,
        event_type: str,
        title: str,
        summary: str,
        incident_id: str | None = None,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
        actionable: bool = False,
    ) -> dict[str, Any]:
        """Format standard structured JSON for generic webhooks (Teams, PagerDuty, etc.)."""
        return {
            "version": "1.0",
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "severity": severity,
            "incident_id": incident_id,
            "actionable": actionable,
            "attributes": fields or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "OpsPilot Multi-Agent System",
        }

    def _post_http(self, url: str, payload: dict[str, Any]) -> tuple[bool, str]:
        """Perform HTTP POST with short timeout and robust error trapping."""
        if not url:
            return False, "URL empty"
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpsPilot-ChatOps/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                status_code = resp.status
                return (status_code in (200, 204)), f"HTTP {status_code}"
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}: {exc.reason}"
        except Exception as exc:
            return False, f"Delivery error: {type(exc).__name__}"

    def dispatch(
        self,
        event_type: str,
        title: str,
        summary: str,
        incident_id: str | None = None,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
        actionable: bool = False,
    ) -> dict[str, Any]:
        """Dispatch formatted ChatOps notifications across configured platforms."""
        if not self.enabled:
            return {"status": "disabled", "message": "ChatOps notifications are currently disabled."}

        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        slack_payload = self.build_slack_payload(
            event_type, title, summary, incident_id, severity, fields, actionable
        )
        discord_payload = self.build_discord_payload(
            event_type, title, summary, incident_id, severity, fields, actionable
        )
        generic_payload = self.build_generic_payload(
            event_type, title, summary, incident_id, severity, fields, actionable
        )

        delivery_results: dict[str, dict[str, Any]] = {}

        # 1. Slack
        if self.slack_webhook_url:
            ok, msg = self._post_http(self.slack_webhook_url, slack_payload)
            delivery_results["slack"] = {"status": "delivered" if ok else "failed", "detail": msg}
        else:
            delivery_results["slack"] = {"status": "simulated", "detail": "Simulation mode (no webhook URL)"}

        # 2. Discord
        if self.discord_webhook_url:
            ok, msg = self._post_http(self.discord_webhook_url, discord_payload)
            delivery_results["discord"] = {"status": "delivered" if ok else "failed", "detail": msg}
        else:
            delivery_results["discord"] = {"status": "simulated", "detail": "Simulation mode (no webhook URL)"}

        # 3. Generic
        if self.generic_webhook_url:
            ok, msg = self._post_http(self.generic_webhook_url, generic_payload)
            delivery_results["generic"] = {"status": "delivered" if ok else "failed", "detail": msg}
        else:
            delivery_results["generic"] = {"status": "simulated", "detail": "Simulation mode (no webhook URL)"}

        # Aggregate record
        record: dict[str, Any] = {
            "event_id": event_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "incident_id": incident_id,
            "severity": severity,
            "actionable": actionable,
            "delivery": delivery_results,
            "slack_preview": slack_payload,
            "discord_preview": discord_payload,
            "generic_preview": generic_payload,
        }

        # Persist to local JSONL log and in-memory history
        with self.lock:
            self.history.appendleft(record)

        self._append_log(record)

        # Record metrics safely
        for platform, res in delivery_results.items():
            self._record_telemetry(platform, event_type, res.get("status", "simulated"))

        return record

    def _append_log(self, record: dict[str, Any]) -> None:
        path = _get_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _CHATOPS_LOCK, path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Could not persist ChatOps log entry: %s", exc)

    def _record_telemetry(self, platform: str, event_type: str, status: str) -> None:
        try:
            safe_platform = platform if platform in ALLOWED_PLATFORMS else "other"
            safe_event = event_type if event_type in ALLOWED_EVENTS else "other"
            safe_status = status if status in ALLOWED_STATUSES else "other"
            app_metrics.record_chatops_notification(safe_platform, safe_event, safe_status)
        except Exception:
            pass

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recently dispatched notifications."""
        with self.lock:
            return list(self.history)[:limit]

    # Pre-packaged event helpers
    def notify_incident_alert(self, incident: dict[str, Any]) -> dict[str, Any]:
        """Broadcast an alert when an incident is diagnosed."""
        inc_id = incident.get("incident_id")
        scenario = incident.get("scenario", "GENERAL_INCIDENT")
        root_cause = incident.get("root_cause") or "Root cause under active investigation."
        action = (incident.get("recommended_action") or {}).get("action") or "investigate"

        return self.dispatch(
            event_type="incident_alert",
            title=f"Incident Diagnosed: {scenario}",
            summary=f"Automated incident analysis for Calculator service detected {scenario}.",
            incident_id=inc_id,
            severity="warning",
            fields={
                "scenario": scenario,
                "root_cause": str(root_cause)[:200],
                "proposed_action": action,
                "current_version": incident.get("current_version", "1.0"),
            },
            actionable=False,
        )

    def notify_approval_requested(self, incident: dict[str, Any]) -> dict[str, Any]:
        """Broadcast an interactive approval card with buttons."""
        inc_id = incident.get("incident_id")
        remediation = incident.get("proposed_remediation") or incident.get("recommended_action") or {}
        action = remediation.get("action", "rollback")
        target_version = remediation.get("target_version") or remediation.get("to_version", "1.0")
        rationale = remediation.get("rationale") or "Autonomous remediation plan prepared by Remediation Agent."

        return self.dispatch(
            event_type="approval_requested",
            title="Human Approval Required for Remediation",
            summary=f"Remediation Agent requests human authorization to execute '{action.upper()}' to v{target_version}.",
            incident_id=inc_id,
            severity="warning",
            fields={
                "action": action.upper(),
                "target_version": f"v{target_version}",
                "rationale": str(rationale)[:200],
                "current_version": incident.get("current_version", "1.0"),
            },
            actionable=True,
        )

    def notify_decision_recorded(
        self,
        incident_id: str,
        decision: str,
        reviewed_by: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Broadcast confirmation of an approval or rejection."""
        approved = decision.lower() == "approve"
        title = "Remediation Approved" if approved else "Remediation Rejected"
        summary = (
            f"Human reviewer '{reviewed_by}' APPROVED the remediation action."
            if approved
            else f"Human reviewer '{reviewed_by}' REJECTED the remediation action."
        )

        outcome_status = ((result or {}).get("outcome") or {}).get("status", "completed" if approved else "rejected")

        return self.dispatch(
            event_type="decision_recorded",
            title=title,
            summary=summary,
            incident_id=incident_id,
            severity="success" if approved else "info",
            fields={
                "reviewed_by": reviewed_by,
                "decision": decision.upper(),
                "outcome_status": outcome_status,
            },
            actionable=False,
        )

    def notify_incident_resolved(self, incident: dict[str, Any]) -> dict[str, Any]:
        """Broadcast resolution confirmation."""
        inc_id = incident.get("incident_id")
        current_version = incident.get("current_version", "1.0")

        return self.dispatch(
            event_type="incident_resolved",
            title="Incident Mitigated and Verified",
            summary=f"Calculator service recovered to healthy state (v{current_version}).",
            incident_id=inc_id,
            severity="success",
            fields={
                "version": current_version,
                "status": "HEALTHY",
            },
            actionable=False,
        )

    def notify_test_ping(self, platform: str = "all") -> dict[str, Any]:
        """Fire a test notification to verify connectivity."""
        return self.dispatch(
            event_type="test_ping",
            title="OpsPilot ChatOps Test Ping",
            summary="Verification message sent from OpsPilot Multi-Agent Control Center.",
            incident_id=f"test-{uuid.uuid4().hex[:6]}",
            severity="info",
            fields={
                "platform_target": platform,
                "gateway_status": "ONLINE",
            },
            actionable=False,
        )


_CLIENT = ChatOpsClient()


def get_chatops_client() -> ChatOpsClient:
    return _CLIENT
