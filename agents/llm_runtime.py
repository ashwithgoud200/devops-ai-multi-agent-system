"""Resource-conscious, validated Ollama runtime for role-specific DevOps models.

Models are requested one at a time and unloaded after each request by default.
LLM output is advisory only; deterministic policy and approval gates remain
responsible for all actions.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "models.json"
_LOCK = threading.Lock()

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Each finding cites its exact evidence JSON path and value, or is "
                "explicitly labeled Unverified/Insufficient evidence."
            ),
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "recommended_checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "findings", "confidence", "recommended_checks"],
    "additionalProperties": False,
}
MAX_LOG_EVENTS_IN_PROMPT = 12
MAX_DIAGNOSTIC_CONTENT = 2000
REQUIRED_FIELDS = {"summary", "findings", "confidence", "recommended_checks"}


def load_config() -> dict[str, Any]:
    path = Path(os.getenv("DEVOPS_MODEL_CONFIG", str(DEFAULT_CONFIG)))
    with path.open(encoding="utf-8") as f:
        config = json.load(f)
    config["enabled"] = os.getenv(
        "DEVOPS_LLM_ENABLED", str(config.get("enabled", False))
    ).lower() in {"1", "true", "yes", "on"}
    if os.getenv("OLLAMA_HOST"):
        config["base_url"] = os.environ["OLLAMA_HOST"]
    return config


def model_for(agent: str, config: dict[str, Any] | None = None) -> str:
    cfg = config or load_config()
    try:
        return cfg["agents"][agent]["model"]
    except KeyError as exc:
        raise ValueError(f"No model configured for agent '{agent}'") from exc


def _parse_json_object(content: str) -> dict[str, Any]:
    """Parse model JSON, tolerating a Markdown fence or surrounding prose."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ollama returned empty content")

    candidate = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.I | re.S)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise ValueError("Response did not contain a JSON object")
        depth = 0
        in_string = False
        escaped = False
        end = None
        for index in range(start, len(candidate)):
            char = candidate[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            raise ValueError("Response contains truncated or unbalanced JSON")
        try:
            parsed = json.loads(candidate[start:end])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Response JSON must be an object")
    missing = [key for key in REQUIRED_FIELDS if key not in parsed]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))
    unexpected = sorted(set(parsed) - REQUIRED_FIELDS)
    if unexpected:
        raise ValueError("Unexpected fields: " + ", ".join(unexpected))
    if not isinstance(parsed["summary"], str):
        raise ValueError("summary must be a string")
    if not isinstance(parsed["findings"], list) or not all(
        isinstance(item, str) for item in parsed["findings"]
    ):
        raise ValueError("findings must be an array of strings")
    if not isinstance(parsed["recommended_checks"], list) or not all(
        isinstance(item, str) for item in parsed["recommended_checks"]
    ):
        raise ValueError("recommended_checks must be an array of strings")
    confidence = parsed["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")

    return {
        "summary": parsed["summary"].strip(),
        "findings": parsed["findings"],
        "confidence": float(confidence),
        "recommended_checks": parsed["recommended_checks"],
    }


def _redact_sensitive_content(text: Any) -> str:
    value = str(text or "")
    patterns = (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"}]+", r"\1[REDACTED]"),
        (
            r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
            r"password|secret)[\"']?\s*:\s*[\"']?)[^\"',}\s]+",
            r"\1[REDACTED]",
        ),
        (
            r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
            r"password|secret)\b\s*[:=]\s*)[^\s,;\"}]+",
            r"\1[REDACTED]",
        ),
        (r"(?i)\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_KEY]"),
    )
    for pattern, replacement in patterns:
        value = re.sub(pattern, replacement, value)
    return value


def _redact_diagnostic(text: Any, limit: int = MAX_DIAGNOSTIC_CONTENT) -> tuple[str, bool]:
    value = _redact_sensitive_content(text)
    truncated = len(value) > limit
    if truncated:
        value = value[:limit] + "…[truncated]"
    return value, truncated


def _prompt_evidence(evidence: Any) -> Any:
    """Bound repetitive logs while preserving a valid, auditable JSON payload."""
    if not isinstance(evidence, dict):
        return evidence
    bounded = dict(evidence)
    logs = evidence.get("logs")
    if not isinstance(logs, dict) or not isinstance(logs.get("events"), list):
        return bounded
    events = logs["events"]
    if len(events) <= MAX_LOG_EVENTS_IN_PROMPT:
        return bounded

    deployment_indices = [
        index for index, event in enumerate(events)
        if isinstance(event, dict)
        and re.fullmatch(
            r"\s*(?:deployed|rolled back to)\s+v?[A-Za-z0-9][A-Za-z0-9._+-]*\s*",
            str(event.get("msg", "")),
            re.IGNORECASE,
        )
    ]
    selected_indices = set(deployment_indices[-4:])
    alert_indices = [
        index for index, event in enumerate(events)
        if isinstance(event, dict)
        and index not in selected_indices
        and str(event.get("level", "")).upper() in {"ERROR", "WARN"}
    ]
    remaining = MAX_LOG_EVENTS_IN_PROMPT - len(selected_indices)
    selected_indices.update(alert_indices[-remaining:] if remaining > 0 else [])
    for index in range(len(events) - 1, -1, -1):
        if len(selected_indices) >= MAX_LOG_EVENTS_IN_PROMPT:
            break
        selected_indices.add(index)
    selected = [events[index] for index in sorted(selected_indices)]
    bounded_logs = dict(logs)
    bounded_logs["events"] = selected
    bounded_logs["prompt_window"] = {
        "included_event_count": len(selected),
        "omitted_event_count": len(events) - len(selected),
        "selection": "recent explicit deploy/rollback events, errors and warnings, then recent events",
    }
    bounded["logs"] = bounded_logs
    return bounded


def _build_messages(
    agent: str, task: str, evidence: Any, config: dict[str, Any]
) -> list[dict[str, str]]:
    role = config["agents"][agent].get(
        "role", f"Analyze DevOps evidence for {agent}"
    )
    system = (
        "You are a cautious DevOps specialist. Use only supplied evidence. "
        "Follow this order: (1) extract directly observed facts, (2) compare "
        "relevant observations and timestamps, (3) label any explanation as an "
        "unconfirmed hypothesis, (4) name only genuinely unavailable relevant "
        "evidence, and (5) recommend checks without executing them. "
        "An unavailable source never makes a different source unavailable. "
        "Prioritize supplied values over generic missing-source notices. "
        "For each factual finding, include its exact evidence JSON path and "
        "observed value. Never invent or estimate metrics, percentages, "
        "thresholds, timestamps, deployment events, or facts. Do not use general "
        "industry thresholds as application-configured thresholds. Label claims "
        "that cannot be tied to evidence 'Unverified' and explain the missing "
        "evidence. Correlation is not causation; confidence is not proof. Do not "
        "claim to have run tools or inspected systems. If verified_observations "
        "is supplied, use it as a deterministic index of source-derived facts, "
        "retain its source paths/timestamps, and do not infer beyond those facts. "
        "When relevant evidence is "
        "genuinely insufficient, begin that finding with 'Insufficient evidence:'. "
        "For Docker claims, cite exact docker.containers paths and never invent "
        "container IDs, names, health, restart counts, or resource values. Null "
        "or unavailable values are not zero. Never issue commands or authorize changes. Return only the "
        "required JSON object with a concise summary, evidence-grounded findings, "
        "confidence from 0 to 1, and advisory recommended_checks."
    )
    role_guidance = {
        "monitoring": (
            " Read every supplied metric source independently. Report available "
            "request, success/error, latency, CPU, and memory observations before "
            "mentioning missing host or container metrics. Preserve units and "
            "distinguish host, process, and container values. Compare a baseline "
            "only when the comparison contains compatible observations."
        ),
        "incident": (
            " Build a short chronological account from supplied deployment, "
            "metric, log, health, and container timestamps. State changes and "
            "their temporal relationship; do not claim a root cause from timing "
            "alone. Preserve the exact status, version, values, and log evidence."
        ),
        "code": (
            " Review only supplied code_changes. Tie any defect to the supplied "
            "function/source and failure evidence. Present corrections as "
            "suggestions; never say code was changed or tested unless evidence "
            "explicitly says so."
        ),
        "cicd": (
            " Report deployment status, pipeline status, health-check status, "
            "and post-deployment metrics as separate facts. Missing pipeline "
            "evidence does not negate a supplied deployment or health result. "
            "Never deploy or roll back."
        ),
        "infrastructure": (
            " Report container status and health separately. Include available "
            "CPU, memory, restart, network, and block-I/O observations. Keep "
            "container metrics separate from host/process metrics and do not "
            "infer resource exhaustion from utilization alone."
        ),
        "security": (
            " Use only supplied security-related events. Preserve event timestamps "
            "and source IPs exactly; identify repeated failures and a subsequent "
            "success when present. Distinguish suspicious behavior from confirmed "
            "compromise. Do not infer attacker intent, attack classification, "
            "geolocation, IP reputation, or threat intelligence without explicit "
            "supporting event evidence. Do not describe supplied events as absent."
        ),
    }
    system += role_guidance.get(agent, "")
    user = json.dumps(
        {
            "task": task,
            "specialist_role": role,
            "evidence": _prompt_evidence(evidence),
        },
        ensure_ascii=False,
        default=str,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def analyze(agent: str, task: str, evidence: Any) -> dict[str, Any]:
    """Run a role-specific local model and return validated advisory analysis."""
    try:
        cfg = load_config()
        model = model_for(agent, cfg)
    except Exception as exc:
        return {"status": "configuration_error", "agent": agent, "detail": str(exc)}

    if not cfg.get("enabled", False):
        return {"status": "disabled", "agent": agent, "model": model}

    runtime = cfg.get("runtime", {})
    base_payload = {
        "model": model,
        "format": RESPONSE_SCHEMA,
        "stream": False,
        "keep_alive": runtime.get("keep_alive", "0s"),
        "options": {
            "num_ctx": int(runtime.get("context_length", 2048)),
            "num_predict": int(runtime.get("max_output_tokens", 384)),
            "temperature": float(runtime.get("temperature", 0.1)),
        },
    }
    messages = _build_messages(agent, task, evidence, cfg)
    attempts: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        with _LOCK:
            for attempt_number in (1, 2):
                request_started = time.perf_counter()
                response = requests.post(
                    cfg.get("base_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
                    json={**base_payload, "messages": messages},
                    timeout=float(runtime.get("request_timeout_seconds", 120)),
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Ollama response must be a JSON object")
                message = body.get("message")
                content = message.get("content", "") if isinstance(message, dict) else ""
                validation_error = None
                analysis = None
                if body.get("done_reason") == "length":
                    validation_error = "Model output was truncated at the token limit"
                else:
                    try:
                        analysis = _parse_json_object(content)
                    except ValueError as exc:
                        validation_error = str(exc)
                attempt = {
                    "attempt": attempt_number,
                    "status": "ok" if validation_error is None else "invalid_response",
                    "detail": validation_error,
                    "done_reason": body.get("done_reason"),
                    "total_duration": body.get("total_duration"),
                    "wall_duration_seconds": time.perf_counter() - request_started,
                }
                if validation_error is not None:
                    excerpt, excerpt_truncated = _redact_diagnostic(content)
                    attempt["raw_excerpt"] = excerpt
                    attempt["raw_excerpt_truncated"] = excerpt_truncated
                attempts.append(attempt)
                if validation_error is None:
                    result = {
                        "status": "ok", "agent": agent, "model": model,
                        "content": json.dumps(analysis, ensure_ascii=False),
                        "analysis": analysis,
                        "raw_content": content,
                        "total_duration": sum(
                            attempt["total_duration"]
                            for attempt in attempts
                            if isinstance(attempt.get("total_duration"), (int, float))
                        ),
                        "wall_duration_seconds": time.perf_counter() - started,
                        "attempts": attempts,
                    }
                    if attempt_number == 2:
                        result["retry"] = {
                            "attempted": True,
                            "status": "ok",
                            "detail": "Correction retry returned valid JSON.",
                        }
                        result["initial_validation_error"] = attempts[0]["detail"]
                        result["initial_raw_content"] = attempts[0].get("raw_excerpt", "")
                        result["diagnostic"] = {
                            "validation_error": attempts[0]["detail"],
                            "raw_excerpt": attempts[0].get("raw_excerpt", ""),
                            "raw_excerpt_truncated": attempts[0].get(
                                "raw_excerpt_truncated", False
                            ),
                            "attempt": 1,
                            "retry_status": "ok",
                        }
                    else:
                        result["retry"] = {"attempted": False, "status": "not_needed"}
                    return result
                if attempt_number == 1:
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response failed strict JSON/schema validation: "
                            f"{validation_error}. Return one corrected JSON object only, "
                            "using exactly the required fields and types. Keep summary, "
                            "findings, and recommended_checks concise. Do not add facts."
                        ),
                    })

        return {
            "status": "invalid_response", "agent": agent, "model": model,
            "detail": attempts[-1]["detail"],
            "validation_error": attempts[-1]["detail"],
            "raw_content": attempts[-1].get("raw_excerpt", ""),
            "diagnostic": {
                "validation_error": attempts[-1]["detail"],
                "raw_excerpt": attempts[-1].get("raw_excerpt", ""),
                "raw_excerpt_truncated": attempts[-1].get(
                    "raw_excerpt_truncated", False
                ),
                "attempt_count": len(attempts),
            },
            "attempts": attempts,
            "retry": {
                "attempted": len(attempts) > 1,
                "status": attempts[-1]["status"],
                "detail": attempts[-1]["detail"] if len(attempts) > 1 else None,
            },
            "wall_duration_seconds": time.perf_counter() - started,
            "total_duration": sum(
                attempt["total_duration"]
                for attempt in attempts
                if isinstance(attempt.get("total_duration"), (int, float))
            ),
        }
    except requests.RequestException as exc:
        return {
            "status": "unavailable", "agent": agent, "model": model,
            "detail": str(exc),
            "attempts": attempts,
            "retry": {
                "attempted": len(attempts) > 0,
                "status": "unavailable" if attempts else "not_started",
            },
            "wall_duration_seconds": time.perf_counter() - started,
        }
    except (ValueError, TypeError, AttributeError) as exc:
        return {
            "status": "invalid_response", "agent": agent, "model": model,
            "detail": str(exc),
            "attempts": attempts,
            "retry": {
                "attempted": len(attempts) > 0,
                "status": "invalid_response" if attempts else "not_started",
            },
            "wall_duration_seconds": time.perf_counter() - started,
        }
