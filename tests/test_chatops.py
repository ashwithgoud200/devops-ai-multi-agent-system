"""Unit tests for ChatOps Webhook Gateway, payload builders, and interactive human-in-the-loop decisions."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.chatops_client import ChatOpsClient, get_chatops_client
from calculator_app.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def chatops() -> ChatOpsClient:
    c = get_chatops_client()
    c.configure(slack_url="", discord_url="", generic_url="", enabled=True)
    c.history.clear()
    try:
        yield c
    finally:
        c.configure(slack_url="", discord_url="", generic_url="", enabled=True)
        c.history.clear()


def test_chatops_client_singleton_and_status(chatops: ChatOpsClient):
    assert chatops is get_chatops_client()
    status = chatops.get_status()
    assert status["enabled"] is True
    assert status["simulation_mode"] is True
    assert status["platforms"]["slack"]["configured"] is False
    assert status["platforms"]["discord"]["configured"] is False
    assert status["platforms"]["generic"]["configured"] is False


def test_slack_payload_builder(chatops: ChatOpsClient):
    payload = chatops.build_slack_payload(
        event_type="approval_requested",
        title="Approval Needed",
        summary="Rollback to v1.0",
        incident_id="inc-12345678-abcd",
        severity="warning",
        fields={"target_version": "v1.0", "action": "ROLLBACK"},
        actionable=True,
    )

    assert "blocks" in payload
    blocks = payload["blocks"]
    assert any(b.get("type") == "header" for b in blocks)
    assert any(b.get("type") == "section" and "Rollback to v1.0" in b.get("text", {}).get("text", "") for b in blocks)

    # Verify interactive action buttons
    action_block = next((b for b in blocks if b.get("type") == "actions"), None)
    assert action_block is not None
    elements = action_block.get("elements", [])
    assert len(elements) == 2
    assert elements[0]["action_id"] == "chatops_approve_button"
    assert elements[1]["action_id"] == "chatops_reject_button"
    btn_val = json.loads(elements[0]["value"])
    assert btn_val["incident_id"] == "inc-12345678-abcd"
    assert btn_val["action"] == "approve"


def test_discord_payload_builder(chatops: ChatOpsClient):
    payload = chatops.build_discord_payload(
        event_type="incident_alert",
        title="Incident Alert",
        summary="High error rate detected in div operation",
        incident_id="inc-9999",
        severity="critical",
        fields={"scenario": "ZERO_DIVISION_SPIKE"},
        actionable=False,
    )

    assert "embeds" in payload
    embed = payload["embeds"][0]
    assert embed["title"] == "Incident Alert"
    assert embed["color"] == 0xDC2626  # critical red
    field_names = [f["name"] for f in embed["fields"]]
    assert "Incident ID" in field_names
    assert "Severity" in field_names
    assert "Scenario" in field_names


def test_generic_payload_builder(chatops: ChatOpsClient):
    payload = chatops.build_generic_payload(
        event_type="incident_resolved",
        title="Resolved",
        summary="Service recovered",
        incident_id="inc-1111",
        severity="success",
        fields={"status": "healthy"},
    )

    assert payload["event_type"] == "incident_resolved"
    assert payload["severity"] == "success"
    assert payload["incident_id"] == "inc-1111"
    assert payload["attributes"]["status"] == "healthy"


def test_dispatch_in_simulation_mode(chatops: ChatOpsClient, tmp_path):
    log_file = tmp_path / "chatops_test.jsonl"
    with patch("agents.chatops_client._get_log_path", return_value=log_file):
        record = chatops.dispatch(
            event_type="incident_alert",
            title="Database Latency Spike",
            summary="Postgres connection pool exhausted",
            incident_id="inc-sim-1",
            severity="warning",
            fields={"latency_ms": 450},
        )

        assert record["event_type"] == "incident_alert"
        assert record["delivery"]["slack"]["status"] == "simulated"
        assert record["delivery"]["discord"]["status"] == "simulated"
        assert len(chatops.get_history()) == 1
        assert log_file.exists()
        logged_data = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert logged_data["incident_id"] == "inc-sim-1"


def test_dispatch_with_mocked_http_post(chatops: ChatOpsClient):
    chatops.configure(
        slack_url="https://hooks.slack.com/services/T00/B00/X00",
        discord_url="https://discord.com/api/webhooks/00/xx",
    )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        record = chatops.dispatch(
            event_type="test_ping",
            title="Ping",
            summary="Test ping",
        )

        assert record["delivery"]["slack"]["status"] == "delivered"
        assert record["delivery"]["discord"]["status"] == "delivered"
    chatops.configure(slack_url="", discord_url="")


def test_chatops_api_status_and_history(client: TestClient, chatops: ChatOpsClient):
    resp = client.get("/chatops/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "platforms" in data
    assert "simulation_mode" in data

    # Trigger test dispatch
    post_resp = client.post("/chatops/test")
    assert post_resp.status_code == 200
    test_result = post_resp.json()
    assert test_result["event_type"] == "test_ping"

    # Verify in history
    hist_resp = client.get("/chatops/history")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert len(hist) >= 1
    assert hist[0]["event_type"] == "test_ping"


def test_chatops_api_config_update(client: TestClient, chatops: ChatOpsClient):
    resp = client.post(
        "/chatops/config",
        json={
            "slack_url": "https://hooks.slack.com/test",
            "discord_url": "https://discord.com/test",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["platforms"]["slack"]["configured"] is True
    assert data["platforms"]["discord"]["configured"] is True

    # Reset
    chatops.configure(slack_url="", discord_url="")


def test_chatops_interactive_inbound_api(client: TestClient):
    with patch(
        "agents.chatops_api.decide_incident",
        return_value={
            "status": "completed",
            "incident_id": "test-inc-123",
            "current_version": "1.0",
            "outcome": {"status": "succeeded"},
        },
    ) as mock_decide:
        interactive_resp = client.post(
            "/chatops/interactive",
            json={
                "incident_id": "test-inc-123",
                "decision": "approve",
                "reviewed_by": "slack-oncall-lead",
            },
        )
        assert interactive_resp.status_code == 200
        res_data = interactive_resp.json()
        assert res_data["status"] == "success"
        assert res_data["decision"] == "approve"
        assert res_data["reviewed_by"] == "slack-oncall-lead"
        assert res_data["incident"]["status"] == "completed"
        mock_decide.assert_called_once()
