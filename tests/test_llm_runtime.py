"""Tests for model routing and validated Ollama responses; no server required."""
import json

import requests

from agents import llm_runtime

VALID_ANALYSIS = {
    "summary": "CPU anomaly detected",
    "findings": ["CPU usage is 95 percent"],
    "confidence": 0.9,
    "recommended_checks": ["Inspect process-level CPU usage"],
}


def test_six_agents_have_distinct_model_assignments():
    cfg = llm_runtime.load_config()
    names = [cfg["agents"][name]["model"] for name in (
        "monitoring", "incident", "code", "cicd", "infrastructure", "security"
    )]
    assert len(names) == 6
    assert len(set(names)) == 6


def test_models_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DEVOPS_LLM_ENABLED", raising=False)
    result = llm_runtime.analyze("monitoring", "test", {"errors": 1})
    assert result["status"] == "disabled"
    assert result["model"] == "qwen2.5:3b"


def test_enabled_model_call_uses_json_schema_and_unloads(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": __import__("json").dumps(VALID_ANALYSIS)}}

    captured = {}

    def fake_post(url, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)
    result = llm_runtime.analyze("monitoring", "explain", {"error_rate": 0.9})
    assert result["status"] == "ok"
    assert result["analysis"]["summary"] == VALID_ANALYSIS["summary"]
    assert result["raw_content"] == __import__("json").dumps(VALID_ANALYSIS)
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "never invent" in system_prompt
    assert "exact evidence JSON path" in system_prompt
    assert "Insufficient evidence:" in system_prompt
    assert captured["payload"]["keep_alive"] == "0s"
    assert captured["payload"]["options"]["num_ctx"] == 2048
    assert captured["payload"]["options"]["num_predict"] == 384
    assert captured["payload"]["format"] == llm_runtime.RESPONSE_SCHEMA
    assert captured["url"].endswith("/api/chat")


def test_shared_prompt_prioritizes_observations_and_separates_sources():
    config = llm_runtime.load_config()
    evidence = {
        "metrics": {"status": "ok", "requests": {"div": {"ok": 10, "error": 2}}},
        "docker": {"status": "unavailable"},
        "system_metrics": {"status": "unavailable"},
        "verified_observations": [{
            "statement": "Observed request error count is 2.",
            "source": "metrics.requests.div.error",
            "timestamp": 123,
        }],
    }

    messages = llm_runtime._build_messages(
        "monitoring", "Inspect supplied metrics.", evidence, config
    )
    system = messages[0]["content"].lower()
    prompt_evidence = json.loads(messages[1]["content"])["evidence"]

    assert "extract directly observed facts" in system
    assert "an unavailable source never makes a different source unavailable" in system
    assert "prioritize supplied values" in system
    assert "deterministic index of source-derived facts" in system
    assert "retain its source paths/timestamps" in system
    assert "metrics" in prompt_evidence
    assert prompt_evidence["metrics"]["requests"]["div"] == {"ok": 10, "error": 2}
    assert prompt_evidence["docker"]["status"] == "unavailable"
    assert prompt_evidence["verified_observations"][0]["source"] == (
        "metrics.requests.div.error"
    )


def test_security_specialist_uses_granite_and_security_specific_grounding(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    security_analysis = {
        "summary": "Recorded authentication events require review.",
        "findings": [
            "The supplied log records a suspicious login attempt.",
            "Insufficient evidence: the source address is not recorded.",
        ],
        "confidence": 0.7,
        "recommended_checks": ["Review the relevant authentication records."],
    }

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps(security_analysis)}}

    captured = {}

    def fake_post(url, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)
    evidence = {
        "logs": {
            "source": "synthetic test fixture",
            "events": [{
                "ts": "2026-11-02T00:58:00+05:30",
                "level": "WARN",
                "msg": "Suspicious login attempt observed; source address not recorded.",
            }],
        }
    }

    result = llm_runtime.analyze("security", "Triage recorded events.", evidence)

    assert result["status"] == "ok"
    assert result["model"] == "granite3.1-dense:2b"
    assert result["analysis"] == security_analysis
    assert result["retry"] == {"attempted": False, "status": "not_needed"}
    prompt = captured["payload"]["messages"][0]["content"].lower()
    assert "do not infer" in prompt
    assert "threat intelligence" in prompt
    assert captured["payload"]["format"] == llm_runtime.RESPONSE_SCHEMA


def test_security_specialist_retries_malformed_json_once(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    valid_security = {
        "summary": "Insufficient evidence for attacker attribution.",
        "findings": ["The supplied event records a failed authentication."],
        "confidence": 0.6,
        "recommended_checks": ["Review source authentication logs."],
    }
    responses = iter([
        {"message": {"content": '{"summary":"not complete'}},
        {"message": {"content": json.dumps(valid_security)}},
    ])
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return next(responses)

    def fake_post(url, json, timeout):
        payloads.append(json)
        return Response()

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)

    result = llm_runtime.analyze(
        "security",
        "Triage authentication events.",
        {"logs": {"events": [{"msg": "Authentication failed."}]}},
    )

    assert result["status"] == "ok"
    assert result["retry"]["attempted"] is True
    assert result["retry"]["status"] == "ok"
    assert result["initial_validation_error"] == (
        "Response contains truncated or unbalanced JSON"
    )
    assert len(payloads) == 2
    assert "strict JSON/schema validation" in payloads[1]["messages"][-1]["content"]
    assert payloads[1]["model"] == "granite3.1-dense:2b"


def test_parser_accepts_markdown_fenced_json():
    raw = "```json\n" + __import__("json").dumps(VALID_ANALYSIS) + "\n```"
    parsed = llm_runtime._parse_json_object(raw)
    assert parsed["confidence"] == 0.9
    assert parsed["findings"] == VALID_ANALYSIS["findings"]


def test_parser_rejects_confidence_outside_range():
    bad = dict(VALID_ANALYSIS, confidence=3)
    try:
        llm_runtime._parse_json_object(__import__("json").dumps(bad))
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("Out-of-range confidence should be rejected")


def test_monitoring_and_code_specialist_responses_match_strict_contract():
    for agent in ("monitoring", "code"):
        parsed = llm_runtime._parse_json_object(json.dumps(VALID_ANALYSIS))
        assert set(parsed) == llm_runtime.REQUIRED_FIELDS
        assert parsed["summary"] == "CPU anomaly detected"


def test_parser_rejects_malformed_json_missing_fields_and_wrong_types():
    invalid_responses = (
        ("{not-json", "truncated or unbalanced JSON"),
        (json.dumps({"summary": "missing fields"}), "Missing required fields"),
        (
            json.dumps({**VALID_ANALYSIS, "findings": "not an array"}),
            "findings must be an array of strings",
        ),
    )
    for raw, expected_error in invalid_responses:
        try:
            llm_runtime._parse_json_object(raw)
        except ValueError as exc:
            assert expected_error in str(exc)
        else:
            raise AssertionError(f"Expected schema failure: {expected_error}")


def test_parser_rejects_unexpected_enum_field_instead_of_silently_dropping_it():
    raw = json.dumps({**VALID_ANALYSIS, "severity": "SEVERE"})
    try:
        llm_runtime._parse_json_object(raw)
    except ValueError as exc:
        assert "Unexpected fields: severity" in str(exc)
    else:
        raise AssertionError("Unexpected enum-like fields must fail strict validation")


def test_invalid_response_retries_once_and_preserves_redacted_diagnostic(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    outputs = iter([
        {
            "message": {
                "content": '{"summary":"password=hidden-secret; api_key":"json-secret partial response'
            },
            "done_reason": "stop",
            "total_duration": 10,
        },
        {
            "message": {"content": json.dumps(VALID_ANALYSIS)},
            "done_reason": "stop",
            "total_duration": 20,
        },
    ])
    payloads = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def fake_post(url, json, timeout):
        payloads.append(json)
        return Response(next(outputs))

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)
    result = llm_runtime.analyze("monitoring", "Inspect metrics", {"metrics": {}})

    assert result["status"] == "ok"
    assert result["retry"] == {
        "attempted": True,
        "status": "ok",
        "detail": "Correction retry returned valid JSON.",
    }
    assert result["initial_validation_error"].startswith(
        "Response contains truncated or unbalanced JSON"
    )
    assert "password=[REDACTED]" in result["attempts"][0]["raw_excerpt"]
    assert 'api_key":"[REDACTED]' in result["attempts"][0]["raw_excerpt"]
    assert "hidden-secret" not in result["attempts"][0]["raw_excerpt"]
    assert "json-secret" not in result["attempts"][0]["raw_excerpt"]
    assert result["raw_content"] == json.dumps(VALID_ANALYSIS)
    assert len(payloads) == 2
    assert payloads[0]["model"] == payloads[1]["model"] == "qwen2.5:3b"
    correction_prompt = payloads[1]["messages"][-1]["content"]
    assert "strict JSON/schema validation" in correction_prompt
    assert "Response contains truncated or unbalanced JSON" in correction_prompt


def test_invalid_response_retry_failure_keeps_both_attempt_diagnostics(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    outputs = iter([
        '{"summary":"one',
        '{"summary":"two',
    ])

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": next(outputs)},
                "done_reason": "stop",
                "total_duration": 5,
            }

    monkeypatch.setattr(
        llm_runtime.requests, "post", lambda *args, **kwargs: Response()
    )
    result = llm_runtime.analyze("code", "Review changes", {"code_changes": {}})

    assert result["status"] == "invalid_response"
    assert result["validation_error"].startswith(
        "Response contains truncated or unbalanced JSON"
    )
    assert len(result["attempts"]) == 2
    assert result["retry"]["attempted"] is True
    assert result["retry"]["status"] == "invalid_response"
    assert [attempt["raw_excerpt"] for attempt in result["attempts"]] == [
        '{"summary":"one',
        '{"summary":"two',
    ]


def test_truncated_output_keeps_raw_partial_response_and_retries(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    outputs = iter([
        {
            "message": {"content": '{"summary":"incomplete'},
            "done_reason": "length",
            "total_duration": 5,
        },
        {
            "message": {"content": json.dumps(VALID_ANALYSIS)},
            "done_reason": "stop",
            "total_duration": 5,
        },
    ])

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return next(outputs)

    monkeypatch.setattr(
        llm_runtime.requests, "post", lambda *args, **kwargs: Response()
    )
    result = llm_runtime.analyze("monitoring", "Review metrics", {})

    assert result["status"] == "ok"
    assert result["attempts"][0]["detail"] == (
        "Model output was truncated at the token limit"
    )
    assert result["initial_raw_content"] == '{"summary":"incomplete'
    assert result["retry"]["status"] == "ok"


def test_ollama_unavailable_does_not_retry(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    calls = []

    def fail_request(*args, **kwargs):
        calls.append(True)
        raise requests.ConnectionError("Ollama is unavailable")

    monkeypatch.setattr(llm_runtime.requests, "post", fail_request)
    result = llm_runtime.analyze("code", "Review changes", {})

    assert result["status"] == "unavailable"
    assert "Ollama is unavailable" in result["detail"]
    assert result["retry"]["attempted"] is False
    assert len(calls) == 1


def test_prompt_evidence_keeps_json_valid_and_bounds_repetitive_logs(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")
    evidence = {
        "logs": {
            "status": "ok",
            "events": [
                {"ts": -1, "level": "INFO", "msg": "deployed v1.1"},
                *[
                {"ts": index, "level": "ERROR", "msg": f"error-{index}"}
                for index in range(100)
                ],
            ],
        }
    }
    payloads = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps(VALID_ANALYSIS)}}

    def fake_post(url, json, timeout):
        payloads.append(json)
        return Response()

    monkeypatch.setattr(llm_runtime.requests, "post", fake_post)
    result = llm_runtime.analyze("code", "Review logs", evidence)

    user_payload = json.loads(payloads[0]["messages"][1]["content"])
    prompt_logs = user_payload["evidence"]["logs"]
    assert result["status"] == "ok"
    assert len(prompt_logs["events"]) == llm_runtime.MAX_LOG_EVENTS_IN_PROMPT
    assert prompt_logs["events"][0]["msg"] == "deployed v1.1"
    assert prompt_logs["prompt_window"]["omitted_event_count"] == 89
    assert "}" in payloads[0]["messages"][1]["content"]


def test_truncated_model_response_is_not_reported_as_success(monkeypatch):
    monkeypatch.setenv("DEVOPS_LLM_ENABLED", "true")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "{}"}, "done_reason": "length"}

    monkeypatch.setattr(llm_runtime.requests, "post", lambda *a, **k: Response())
    result = llm_runtime.analyze("cicd", "analyze deploy", {})
    assert result["status"] == "invalid_response"
    assert "truncated" in result["detail"]
