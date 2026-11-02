"""Sequential live evaluation of the six configured Ollama specialists.

Run with DEVOPS_LLM_ENABLED=true in the process environment. The harness uses
synthetic evidence, invokes only agents.llm_runtime, and never executes actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import evidence_extractor, graph, llm_runtime  # noqa: E402

EXPECTED_MODELS = {
    "monitoring": "qwen2.5:3b",
    "incident": "llama3.2:3b",
    "code": "qwen2.5-coder:3b",
    "cicd": "stablelm-zephyr:3b",
    "infrastructure": "phi3.5:3.8b",
    "security": "granite3.1-dense:2b",
}
AGENT_ORDER = tuple(EXPECTED_MODELS)
REPORT_PATH = ROOT / "reports" / "six_agent_live_evaluation.md"
JSON_REPORT_PATH = ROOT / "reports" / "six_agent_live_evaluation.json"
GROUNDING_REPORT_PATH = ROOT / "reports" / "six_agent_grounding_improvement.md"
GROUNDING_JSON_PATH = ROOT / "reports" / "six_agent_grounding_improvement.json"
PROMPT7_REPORT_PATH = ROOT / "reports" / "prompt_7_evidence_extraction.md"
PROMPT7_JSON_PATH = ROOT / "reports" / "prompt_7_evidence_extraction.json"
PROMPT7_1_REPORT_PATH = ROOT / "reports" / "prompt_7_1_live_evaluation.md"
PROMPT7_1_JSON_PATH = ROOT / "reports" / "prompt_7_1_live_evaluation.json"
HISTORICAL_BASELINE = {
    "run_utc": "2026-11-01T21:11:29.548160+00:00",
    "summary": {
        "total": 6,
        "inference_ok": 6,
        "schema_valid": 6,
        "skipped": 0,
        "failed": 0,
        "total_inference_seconds": 40.442,
    },
    "agents": [
        {"agent": "monitoring", "model": "qwen2.5:3b", "latency_seconds": 6.16, "retry_count": 0, "reported_result": "PARTIAL"},
        {"agent": "incident", "model": "llama3.2:3b", "latency_seconds": 6.55, "retry_count": 0, "reported_result": "PARTIAL"},
        {"agent": "code", "model": "qwen2.5-coder:3b", "latency_seconds": 6.51, "retry_count": 0, "reported_result": "PARTIAL"},
        {"agent": "cicd", "model": "stablelm-zephyr:3b", "latency_seconds": 4.60, "retry_count": 0, "reported_result": "PARTIAL"},
        {"agent": "infrastructure", "model": "phi3.5:3.8b", "latency_seconds": 8.17, "retry_count": 0, "reported_result": "PARTIAL"},
        {"agent": "security", "model": "granite3.1-dense:2b", "latency_seconds": 8.50, "retry_count": 0, "reported_result": "PARTIAL"},
    ],
    "sequential_overlap_detected": False,
    "interpretation": (
        "The original run had six schema-valid responses and no overlap, but "
        "the harness labeled every response PARTIAL without checking acceptance "
        "criteria. These values come from the original report and are not a "
        "content-quality score."
    ),
}


def _ts() -> float:
    return time.time()


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _scenario_data() -> dict[str, dict[str, Any]]:
    now = _ts()
    security_timestamps = [_iso_timestamp(now - offset) for offset in (45, 40, 35, 30)]
    return {
        "monitoring": {
            "task": (
                "Assess the supplied synthetic Prometheus observations. Identify "
                "the measured request/error rates, p95 latency, and process CPU. "
                "Keep observations separate from possible explanations; do not "
                "claim a confirmed root cause. Recommend checks only; take no action."
            ),
            "evidence": {
                "source": "synthetic Prometheus evaluation fixture",
                "timestamp": now,
                "prometheus": {
                    "status": "ok",
                    "source": "synthetic Prometheus evaluation fixture",
                    "timestamp": now,
                    "metrics": {
                        "request_rate": {
                            "status": "ok",
                            "unit": "requests/second",
                            "observations": [
                                {
                                    "labels": {"op": "div", "status": "ok"},
                                    "latest_timestamp": now,
                                    "latest_value": 10,
                                    "stale": False,
                                    "values": [{"timestamp": now, "value": 10, "stale": False}],
                                },
                                {
                                    "labels": {"op": "div", "status": "error"},
                                    "latest_timestamp": now,
                                    "latest_value": 2,
                                    "stale": False,
                                    "values": [{"timestamp": now, "value": 2, "stale": False}],
                                },
                            ],
                        },
                        "http_error_rate": {
                            "status": "ok",
                            "unit": "percent",
                            "observations": [{
                                "labels": {},
                                "latest_timestamp": now,
                                "latest_value": 16.6667,
                                "stale": False,
                                "values": [{"timestamp": now, "value": 16.6667, "stale": False}],
                            }],
                        },
                        "latency_p95": {
                            "status": "ok",
                            "unit": "seconds",
                            "observations": [{
                                "labels": {},
                                "latest_timestamp": now,
                                "latest_value": 0.85,
                                "stale": False,
                                "values": [{"timestamp": now, "value": 0.85, "stale": False}],
                            }],
                        },
                        "cpu_utilization": {
                            "status": "ok",
                            "unit": "percent_of_one_cpu",
                            "observations": [{
                                "labels": {},
                                "latest_timestamp": now,
                                "latest_value": 88,
                                "stale": False,
                                "values": [{"timestamp": now, "value": 88, "stale": False}],
                            }],
                        },
                        "memory_usage": {
                            "status": "ok",
                            "unit": "bytes",
                            "observations": [{
                                "labels": {},
                                "latest_timestamp": now,
                                "latest_value": 78643200,
                                "stale": False,
                                "values": [{"timestamp": now, "value": 78643200, "stale": False}],
                            }],
                        },
                    },
                },
                "unavailable": [
                    "No synthetic evidence supplied for host CPU, container metrics, or root cause."
                ],
            },
            "query": "review monitoring metrics",
            "comparison": {"regression_signal": False, "deployment_changed": False},
            "expected_criteria": [
                "Reports the observed error request rate and elevated error behavior.",
                "Reports the observed 850 ms p95 latency.",
                "Reports 88% process CPU as an observation, not a proven cause.",
                "Does not invent host/container measurements or assert a confirmed root cause.",
            ],
        },
        "incident": {
            "task": (
                "Triage this synthetic incident. Correlate deployment, counters, "
                "latency, and timestamped logs. Distinguish temporal correlation "
                "from confirmed causation. Recommend investigation only."
            ),
            "evidence": {
                "source": "synthetic incident fixture",
                "captured_at": now,
                "deployment": {
                    "source": "synthetic deployment record",
                    "previous_version": "1.0",
                    "current_version": "1.1",
                    "deployment_timestamp": now - 300,
                    "deployment_status": "completed",
                },
                "metrics": {
                    "source": "synthetic Prometheus observations",
                    "timestamp": now,
                    "request_counters": {
                        "status": "ok",
                        "requests": {"div": {"error": 35, "ok": 65}},
                    },
                    "baseline_error_count": 2,
                    "current_error_count": 35,
                    "baseline_p95_latency_ms": 100,
                    "current_p95_latency_ms": 900,
                },
                "logs": {
                    "status": "ok",
                    "source": "synthetic application logs",
                    "events": [
                        {"ts": now - 120, "level": "ERROR", "msg": "application timeout while handling request"},
                        {"ts": now - 90, "level": "ERROR", "msg": "application timeout while handling request"},
                        {"ts": now - 30, "level": "ERROR", "msg": "application timeout while handling request"},
                    ],
                },
                "unavailable": ["No infrastructure-failure evidence was supplied."],
            },
            "query": "diagnose incident after deployment",
            "comparison": {"regression_signal": True, "deployment_changed": True},
            "expected_criteria": [
                "Connects the version transition and increased errors/latency with repeated timeout logs.",
                "Treats the timing as correlation rather than confirmed causation.",
                "Does not invent infrastructure failure evidence.",
                "Recommends verification without executing rollback or remediation.",
            ],
        },
        "code": {
            "task": (
                "Review only the supplied synthetic source snippet and observed "
                "stack trace. Identify the edge case and suggest a safe code-level "
                "correction without claiming it has been applied. Do not invent "
                "other code changes."
            ),
            "evidence": {
                "code_changes": {
                    "status": "provided",
                    "source": "synthetic test snippet; no repository change made",
                    "source_code": (
                        "def calculate_average(values):\n"
                        "    return sum(values) / len(values)\n"
                    ),
                    "observed_failure": "An empty input list causes division by zero.",
                    "stack_trace": "Synthetic stack trace points to the division operation.",
                    "modification_status": "No source-code modification has been made.",
                },
                "unavailable": ["No other code changes or runtime telemetry were supplied."],
            },
            "query": "review this synthetic code incident",
            "comparison": {"regression_signal": True, "deployment_changed": False},
            "expected_criteria": [
                "Identifies the empty-list division-by-zero edge case.",
                "Suggests a safe correction while stating it is only a suggestion.",
                "Does not claim any change was applied or invent additional modifications.",
            ],
        },
        "cicd": {
            "task": (
                "Analyze this synthetic deployment evidence. Distinguish deployment "
                "success from application health and pipeline status. Recommend "
                "verification steps only; do not deploy or roll back."
            ),
            "evidence": {
                "deployment": {
                    "source": "synthetic deployment record",
                    "previous_version": "1.0",
                    "current_version": "1.1",
                    "deployment_status": "completed successfully",
                    "timestamp": now - 300,
                },
                "application": {
                    "source": "synthetic application observations",
                    "error_rate_percent": 16.6667,
                    "post_deployment_error_rate_increased": True,
                    "health_http_status": 200,
                    "health_status": "ok",
                },
                "pipeline": {
                    "status": "unavailable",
                    "detail": "No CI pipeline failure evidence is available.",
                },
                "unavailable": ["Pipeline failure details are unavailable."],
            },
            "query": "review deployment evidence",
            "comparison": {"regression_signal": True, "deployment_changed": True},
            "expected_criteria": [
                "Identifies successful deployment followed by increased errors.",
                "Does not claim pipeline failure.",
                "Distinguishes HTTP 200/health status from error-rate behavior.",
                "Recommends investigation without executing deployment or rollback.",
            ],
        },
        "infrastructure": {
            "task": (
                "Interpret this synthetic Docker and process telemetry. Keep "
                "container and host-process memory separate. State resource "
                "pressure as an observation and do not invent root causes or "
                "unprovided metrics. Recommend checks only."
            ),
            "evidence": {
                "docker": {
                    "status": "ok",
                    "source": "synthetic Docker telemetry fixture",
                    "timestamp": now,
                    "containers": [{
                        "id": "synthetic-container-001",
                        "name": "synthetic-calculator",
                        "status": "running",
                        "health_status": "healthy",
                        "restart_count": 0,
                        "cpu_usage_percent": 92,
                        "memory_usage_bytes": 734003200,
                        "memory_usage_mib": 700,
                    }],
                },
                "process": {
                    "source": "synthetic process metrics fixture",
                    "timestamp": now,
                    "host_process_memory_bytes": 62914560,
                    "host_process_memory_mib": 60,
                },
                "unavailable": [
                    "No disk, network, or broader host utilization measurements were supplied."
                ],
            },
            "query": "review infrastructure resource telemetry",
            "comparison": {"regression_signal": False, "deployment_changed": False},
            "expected_criteria": [
                "Reports running/healthy status and zero restarts accurately.",
                "Identifies 92% CPU as observed resource pressure without calling the container unhealthy.",
                "Distinguishes 700 MiB container memory from 60 MiB process memory.",
                "Does not invent disk, network, or root-cause evidence.",
            ],
        },
        "security": {
            "task": (
                "Triage only the synthetic authentication events. Identify the "
                "recorded failed and successful login sequence. Treat suspicious "
                "intent as a hypothesis, not confirmed compromise. Do not invent "
                "geolocation, reputation, threat intelligence, or attacker attribution."
            ),
            "evidence": {
                "logs": {
                    "status": "ok",
                    "source": "explicitly synthetic security log fixture",
                    "events": [
                        {"ts": security_timestamps[0], "level": "WARN", "msg": "authentication failed login user=demo source_ip=192.0.2.10"},
                        {"ts": security_timestamps[1], "level": "WARN", "msg": "authentication failed login user=demo source_ip=192.0.2.10"},
                        {"ts": security_timestamps[2], "level": "WARN", "msg": "authentication failed login user=demo source_ip=192.0.2.10"},
                        {"ts": security_timestamps[3], "level": "INFO", "msg": "authentication successful login user=demo source_ip=192.0.2.10"},
                    ],
                },
                "security_telemetry": {
                    "status": "unavailable",
                    "detail": "No threat-intelligence or account-compromise evidence supplied.",
                },
            },
            "query": "triage suspicious security login events",
            "comparison": {"regression_signal": False, "deployment_changed": False},
            "expected_criteria": [
                "Identifies the repeated failed logins and subsequent successful login.",
                "Treats the sequence as potentially suspicious, not confirmed malicious or compromised.",
                "Preserves supplied timestamps and the synthetic source IP accurately.",
                "Does not invent geolocation, reputation, or threat-intelligence claims.",
            ],
        },
    }


def _routing_state(name: str, scenario: dict[str, Any]) -> dict[str, Any]:
    fixture = scenario["evidence"]
    evidence: dict[str, Any] = {
        "captured_at": _ts(),
        "health": {"status": "unavailable", "detail": "Not supplied in this fixture"},
        "metrics": {"status": "unavailable", "detail": "Not supplied in this fixture"},
        "system_metrics": {
            "status": "unavailable",
            "detail": "Not supplied in this fixture",
            "measurements": {},
        },
        "version": {"status": "unavailable", "detail": "Not supplied in this fixture"},
        "logs": {
            "status": "unavailable",
            "events": [],
            "detail": "Not supplied in this fixture",
        },
        "docker": {
            "status": "unavailable",
            "containers": [],
            "detail": "Not supplied in this fixture",
        },
        "prometheus": {
            "status": "unavailable",
            "metrics": {},
            "detail": "Not supplied in this fixture",
        },
    }
    current_time = _ts()
    if name == "monitoring":
        evidence["prometheus"] = fixture["prometheus"]
    elif name == "incident":
        deployment = fixture["deployment"]
        metrics = fixture["metrics"]
        baseline_time = current_time - 360
        evidence.update({
            "captured_at": current_time,
            "health": {"status": "unavailable", "detail": "Not supplied in this fixture"},
            "metrics": {
                "status": "ok",
                "source": metrics["source"],
                "timestamp": current_time,
                "requests": {
                    "div": {
                        "error": metrics["current_error_count"],
                        "ok": 100 - metrics["current_error_count"],
                    }
                },
                "latency_observations": {
                    "by_operation": {
                        "div": metrics["current_p95_latency_ms"] / 1000,
                    }
                },
            },
            "version": {
                "status": "ok",
                "source": deployment["source"],
                "timestamp": current_time,
                "data": {
                    "version": deployment["current_version"],
                    "deployment_status": deployment["deployment_status"],
                    "history": [
                        {
                            "version": deployment["previous_version"],
                            "ts": deployment["deployment_timestamp"] - 60,
                        },
                        {
                            "version": deployment["current_version"],
                            "ts": deployment["deployment_timestamp"],
                        },
                    ],
                },
            },
            "logs": fixture["logs"],
        })
        baseline = {
            "captured_at": baseline_time,
            "health": {"status": "unavailable"},
            "metrics": {
                "status": "ok",
                "timestamp": baseline_time,
                "requests": {
                    "div": {
                        "error": metrics["baseline_error_count"],
                        "ok": 100 - metrics["baseline_error_count"],
                    }
                },
                "latency_observations": {
                    "by_operation": {
                        "div": metrics["baseline_p95_latency_ms"] / 1000,
                    }
                },
            },
            "version": {
                "status": "ok",
                "data": {
                    "version": deployment["previous_version"],
                    "history": [{
                        "version": deployment["previous_version"],
                        "ts": deployment["deployment_timestamp"] - 60,
                    }],
                },
            },
            "logs": {
                "status": "ok",
                "timestamp": baseline_time,
                "events": [],
            },
        }
        comparison = graph._compare_snapshots(
            {"status": "ok", "snapshot": baseline},
            evidence,
        )
        evidence["baseline_comparison"] = comparison
        return {
            "query": scenario["query"],
            "evidence": evidence,
            "comparison": comparison,
        }
    elif name == "cicd":
        deployment = fixture["deployment"]
        application = fixture["application"]
        evidence.update({
            "version": {
                "status": "ok",
                "source": deployment["source"],
                "timestamp": deployment["timestamp"],
                "data": {
                    "version": deployment["current_version"],
                    "previous_version": deployment["previous_version"],
                    "deployment_status": deployment["deployment_status"],
                    "pipeline": fixture["pipeline"],
                },
            },
            "health": {
                "status": "ok",
                "source": application["source"],
                "timestamp": current_time,
                "data": {
                    "status": application["health_status"],
                    "http_status": application["health_http_status"],
                },
            },
            "metrics": {
                "status": "ok",
                "source": application["source"],
                "timestamp": current_time,
                "error_rate_percent": application["error_rate_percent"],
                "post_deployment_error_rate_increased": application[
                    "post_deployment_error_rate_increased"
                ],
            },
        })
    elif name == "infrastructure":
        evidence.update({
            "docker": fixture["docker"],
            "system_metrics": {
                "status": "unavailable",
                "source": "host telemetry not supplied in this fixture",
                "measurements": {},
            },
            "process": fixture["process"],
        })
    elif name == "code":
        evidence["code_changes"] = fixture["code_changes"]
    elif name == "security":
        evidence["logs"] = fixture["logs"]
    return {
        "query": scenario["query"],
        "evidence": evidence,
        "comparison": scenario["comparison"],
    }


def _expected_installed_tags() -> tuple[list[str], list[str], str]:
    base_url = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        response = requests.get(base_url + "/api/tags", timeout=5)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return [], sorted(set(EXPECTED_MODELS.values())), base_url
    installed = [
        item["name"] for item in body.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    missing = []
    for required in EXPECTED_MODELS.values():
        if required not in installed:
            missing.append(required)
    return installed, sorted(set(missing)), base_url


def _ollama_processes(base_url: str) -> dict[str, Any] | None:
    try:
        response = requests.get(base_url + "/api/ps", timeout=5)
        response.raise_for_status()
        body = response.json()
        return {
            "models": [
                {
                    "name": item.get("name"),
                    "size": item.get("size"),
                    "size_vram": item.get("size_vram"),
                }
                for item in body.get("models", [])
                if isinstance(item, dict)
            ]
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {"error": str(exc)}


def _gpu_info() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "detail": str(exc)}
    if result.returncode:
        return {
            "status": "unavailable",
            "detail": result.stderr.strip() or "nvidia-smi returned an error",
        }
    return {"status": "ok", "reported": result.stdout.strip()}


def _claim_classification(claim: str, validation: dict[str, Any]) -> str:
    lowered = claim.lower()
    if validation["validation_status"] in {"numbers_supported", "evidence_linked"}:
        return "Supported observation / evidence-linked claim"
    if any(token in lowered for token in ("hypothesis", "possible", "may ", "might ", "could ")):
        return "Reasonable hypothesis (unconfirmed)"
    return "Unsupported or unverified claim"


def _safe_report_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_report_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_safe_report_value(child) for child in value]
    if isinstance(value, str):
        return _safe_error_detail(value)
    return value


def _required_observations(
    name: str, scenario: dict[str, Any]
) -> list[dict[str, str]]:
    requirements: dict[str, list[tuple[str, str]]] = {
        "monitoring": [
            ("Successful request rate", r"(?<![\w.])10(?:\.0+)?(?![\w.])"),
            ("Error request rate", r"(?<![\w.])2(?:\.0+)?(?![\w.])"),
            ("Error rate", r"16\.6667"),
            ("P95 latency", r"(?<![\w.])0\.85(?![\w.])"),
            ("Process CPU", r"(?<![\w.])88(?:\.0+)?\s*%?"),
            (
                "Process memory",
                r"(?<![\w.])(?:75\s*MiB|78,?643,?200(?:\s*bytes)?|"
                r"7\.86432e\+?0?7(?:\s*bytes)?)",
            ),
        ],
        "incident": [
            ("Previous version", r"(?<![\w.])1\.0(?![\w.])"),
            ("Current version", r"(?<![\w.])1\.1(?![\w.])"),
            ("Previous error count", r"(?<![\w.])2(?![\w.])"),
            ("Current error count", r"(?<![\w.])35(?![\w.])"),
            ("Baseline latency", r"(?<![\w.])100(?:\s*ms)?"),
            ("Current latency", r"(?<![\w.])900(?:\s*ms)?"),
            ("Timeout log evidence", r"\btimeout"),
        ],
        "code": [
            ("Supplied function", r"\bcalculate_average\b"),
            ("Empty input edge case", r"\bempty\b"),
            ("Division failure", r"\bdivision by zero\b|\bdivide by zero\b"),
        ],
        "cicd": [
            ("Previous version", r"(?<![\w.])1\.0(?![\w.])"),
            ("Current version", r"(?<![\w.])1\.1(?![\w.])"),
            ("Deployment completion", r"\bcompleted\b|\bsuccessful\b"),
            ("Health response", r"(?<![\w.])200(?![\w.])"),
            ("Post-deployment error rate", r"16\.6667"),
        ],
        "infrastructure": [
            ("Container name", r"\bsynthetic-calculator\b"),
            ("Running state", r"\brunning\b"),
            ("Healthy state", r"\bhealthy\b"),
            ("Zero restarts", r"\b0\s+restarts?\b|\brestart count\s*(?:is|=|:)?\s*0\b"),
            ("Container CPU", r"(?<![\w.])92\s*%"),
            ("Container memory", r"(?<![\w.])700\s*MiB"),
            ("Process memory", r"(?<![\w.])60\s*MiB"),
        ],
        "security": [
            ("Synthetic source IP", r"192\.0\.2\.10"),
            ("Repeated failed logins", r"\b(?:3|three)\b.{0,30}\bfailed\b|\brepeated\b.{0,30}\bfailed\b"),
            ("Subsequent successful login", r"\bsuccessful login\b|\bauthentication successful\b"),
        ],
    }
    results = [
        {"requirement": label, "pattern": pattern}
        for label, pattern in requirements[name]
    ]
    if name == "security":
        events = scenario["evidence"]["logs"]["events"]
        results.extend(
            {
                "requirement": f"Event timestamp {event['ts']}",
                "pattern": re.escape(event["ts"]),
            }
            for event in events
        )
    return results


def _material_unsupported_reasons(validation: dict[str, Any]) -> list[str]:
    non_material = (
        "natural-language claim cannot be fully verified",
    )
    return [
        reason for reason in validation.get("reasons", [])
        if not reason.startswith(non_material)
    ]


def _grade_agent(
    name: str,
    scenario: dict[str, Any],
    analysis: dict[str, Any] | None,
    claims: list[dict[str, Any]],
    inference_status: str,
    schema_valid: bool,
    model_mapping_matches: bool,
    routing_selected: bool,
) -> dict[str, Any]:
    response_text = ""
    if isinstance(analysis, dict):
        response_text = "\n".join(
            [str(analysis.get("summary", ""))]
            + [str(item) for item in analysis.get("findings", [])]
            + [str(item) for item in analysis.get("recommended_checks", [])]
        )
    observations = []
    for requirement in _required_observations(name, scenario):
        matched = re.search(requirement["pattern"], response_text, re.IGNORECASE) is not None
        observations.append({**requirement, "identified": matched})
    forbidden_patterns = {
        "monitoring": [r"\b(?:root cause is|caused by)\b"],
        "incident": [r"\bdeployment (?:definitely )?caused\b"],
        "code": [
            r"\b(?:patch|change|fix) (?:was|has been) (?:applied|implemented|tested)\b"
        ],
        "cicd": [r"\bpipeline (?:has )?(?:failed|failure)\b"],
        "infrastructure": [r"\bcontainer\b.{0,40}\bunhealthy\b"],
        "security": [
            r"\bthreat intelligence (?:confirms|shows|verified)\b",
            r"\b(?:geolocated|located in)\b",
            r"\b(?:account|system) (?:is )?compromised\b",
        ],
    }
    prohibited = [
        pattern
        for pattern in forbidden_patterns[name]
        if re.search(pattern, response_text, re.IGNORECASE)
    ]
    material_unsupported = [
        {
            "kind": claim["kind"],
            "text": claim["text"],
            "reasons": _material_unsupported_reasons(claim["validation"]),
        }
        for claim in claims
        if _material_unsupported_reasons(claim["validation"])
    ]
    if inference_status != "ok" or not schema_valid or not model_mapping_matches or not routing_selected:
        result = "FAIL"
    elif (
        any(not item["identified"] for item in observations)
        or prohibited
        or material_unsupported
    ):
        result = "PARTIAL"
    else:
        result = "PASS"
    return {
        "overall_result": result,
        "required_observations": observations,
        "missing_observations": [
            item["requirement"] for item in observations if not item["identified"]
        ],
        "prohibited_claim_patterns": prohibited,
        "material_unsupported_claims": material_unsupported,
    }


def _evaluate_one(
    name: str,
    scenario: dict[str, Any],
    cfg: dict[str, Any],
    base_url: str,
    previous_end: float | None,
    *,
    include_prompt7_evidence: bool = False,
) -> tuple[dict[str, Any], float]:
    model = llm_runtime.model_for(name, cfg)
    route_state = _routing_state(name, scenario)
    if include_prompt7_evidence:
        route_state["evidence_extraction"] = evidence_extractor.validate_extraction(
            evidence_extractor.extract_evidence(
                route_state["evidence"],
                route_state.get("baseline", {"status": "unavailable"}),
                route_state["comparison"],
            )
        )
    selected = graph._select_specialists(route_state)
    specialist_evidence = graph._specialist_evidence(name, route_state)
    prompt_messages = llm_runtime._build_messages(
        name, scenario["task"], specialist_evidence, cfg
    )
    prompt_user = json.loads(prompt_messages[1]["content"])
    prompt_evidence = prompt_user["evidence"]
    source_evidence_json = json.dumps(
        specialist_evidence, ensure_ascii=False, default=str
    )
    prompt_evidence_json = json.dumps(
        prompt_evidence, ensure_ascii=False, default=str
    )
    source_event_count = len(
        specialist_evidence.get("logs", {}).get("events", [])
    ) if isinstance(specialist_evidence.get("logs"), dict) else 0
    prompt_log_window = (
        prompt_evidence.get("logs", {}).get("prompt_window", {})
        if isinstance(prompt_evidence, dict)
        and isinstance(prompt_evidence.get("logs"), dict)
        else {}
    )
    prompt_event_count = len(
        prompt_evidence.get("logs", {}).get("events", [])
    ) if isinstance(prompt_evidence, dict) and isinstance(
        prompt_evidence.get("logs"), dict
    ) else 0

    before_processes = _ollama_processes(base_url)
    start_unix = _ts()
    start_perf = time.perf_counter()
    try:
        result = llm_runtime.analyze(name, scenario["task"], specialist_evidence)
    except Exception as exc:
        result = {
            "status": "harness_error",
            "agent": name,
            "model": model,
            "detail": f"{type(exc).__name__}: {exc}",
            "attempts": [],
            "retry": {"attempted": False, "status": "not_started"},
        }
    end_perf = time.perf_counter()
    end_unix = _ts()
    after_processes = _ollama_processes(base_url)

    result_status = result.get("status", "invalid_result") if isinstance(result, dict) else "invalid_result"
    analysis = result.get("analysis") if isinstance(result, dict) else None
    raw_content = result.get("raw_content", "") if isinstance(result, dict) else ""
    if not raw_content and isinstance(result, dict):
        raw_content = result.get("initial_raw_content", "")
    safe_raw, raw_truncated = llm_runtime._redact_diagnostic(raw_content)

    parse_valid = False
    parse_error = None
    if result_status == "ok" and isinstance(raw_content, str):
        try:
            parsed = llm_runtime._parse_json_object(raw_content)
            parse_valid = parsed == analysis
        except ValueError as exc:
            parse_error = str(exc)

    claims = []
    if isinstance(analysis, dict):
        for field in ("summary", "findings"):
            values = [analysis.get(field)] if field == "summary" else analysis.get(field, [])
            if not isinstance(values, list):
                continue
            for claim in values:
                if not isinstance(claim, str):
                    continue
                validation = graph._validate_finding(claim, specialist_evidence)
                claims.append({
                    "kind": field,
                    "text": llm_runtime._redact_sensitive_content(claim),
                    "classification": _claim_classification(claim, validation),
                    "validation_status": validation["validation_status"],
                    "evidence_refs": validation["evidence_refs"],
                    "reasons": validation["reasons"],
                    "validation": _safe_report_value(validation),
                })
        for recommendation in analysis.get("recommended_checks", []):
            if isinstance(recommendation, str):
                validation = graph._validate_finding(
                    recommendation, specialist_evidence
                )
                material_reasons = _material_unsupported_reasons(validation)
                claims.append({
                    "kind": "recommended_check",
                    "text": llm_runtime._redact_sensitive_content(recommendation),
                    "classification": (
                        "Recommendation with unsupported premise"
                        if material_reasons
                        else "Recommendation (not executed)"
                    ),
                    "validation_status": "unverified" if material_reasons else "advisory",
                    "evidence_refs": validation["evidence_refs"],
                    "reasons": material_reasons,
                    "validation": _safe_report_value(validation),
                })

    elapsed = end_perf - start_perf
    attempts = result.get("attempts", []) if isinstance(result, dict) else []
    actual_model = result.get("model") if isinstance(result, dict) else None
    sequential = previous_end is None or start_perf >= previous_end
    entry = {
        "agent": name,
        "assigned_model": model,
        "reported_model": actual_model,
        "model_mapping_matches": (
            model == EXPECTED_MODELS[name]
            and (actual_model == model if actual_model else result_status == "disabled")
        ),
        "model_available": model in cfg.get("_installed_models", []),
        "routing_selected": name in selected,
        "routing_selected_agents": selected,
        "inference_status": result_status,
        "json_schema_valid": parse_valid,
        "json_parse_error": parse_error,
        "analysis": _safe_report_value(analysis),
        "claims": claims,
        "raw_excerpt": safe_raw,
        "raw_excerpt_truncated": raw_truncated,
        "latency_seconds": elapsed,
        "start_unix": start_unix,
        "end_unix": end_unix,
        "previous_inference_end_perf": previous_end,
        "no_overlap_with_previous": sequential,
        "attempts": attempts,
        "retry": result.get("retry") if isinstance(result, dict) else None,
        "retry_count": max(0, len(attempts) - 1),
        "validation_error": result.get("validation_error") if isinstance(result, dict) else None,
        "error_detail": _safe_error_detail(
            result.get("detail")
            if isinstance(result, dict) else "Runtime returned a non-object"
        ),
        "ollama_processes_before": before_processes,
        "ollama_processes_after": after_processes,
        "expected_criteria": scenario["expected_criteria"],
        "original_synthetic_evidence": _safe_report_value(scenario["evidence"]),
        "graph_input_evidence": _safe_report_value(route_state["evidence"]),
        "graph_shaped_evidence": _safe_report_value(specialist_evidence),
        "prompt_diagnostics": {
            "serialized_graph_evidence_characters": len(source_evidence_json),
            "serialized_prompt_evidence_characters": len(prompt_evidence_json),
            "system_prompt_characters": len(prompt_messages[0]["content"]),
            "user_prompt_characters": len(prompt_messages[1]["content"]),
            "source_log_event_count": source_event_count,
            "prompt_log_event_count": prompt_event_count,
            "omitted_log_event_count": int(
                prompt_log_window.get("omitted_event_count", 0)
            ),
            "log_truncation_applied": bool(
                prompt_log_window.get("omitted_event_count", 0)
            ),
            "messages": _safe_report_value(prompt_messages),
        },
    }
    if include_prompt7_evidence:
        extraction = route_state["evidence_extraction"]
        role_package = specialist_evidence["deterministic_evidence"]
        expected = PROMPT7_REQUIRED_FACTS[name]
        required_results = []
        for requirement in expected:
            extracted_matches = _required_fact_matches(
                extraction["observations"], requirement, include_stale=True
            )
            delivered_matches = _required_fact_matches(
                role_package["observations"], requirement, include_stale=True
            )
            required_results.append({
                "category": requirement[0],
                "metric_or_event": requirement[1],
                "evidence_text_contains": requirement[2],
                "extracted": bool(extracted_matches),
                "delivered": bool(delivered_matches),
                "usable": any(
                    item["status"] in {"observed", "derived", "partial"}
                    for item in delivered_matches
                ),
                "evidence_ids": [
                    item["evidence_id"] for item in extracted_matches
                ],
                "delivered_evidence_ids": [
                    item["evidence_id"] for item in delivered_matches
                ],
                "source_paths": sorted({
                    item["source_path"] for item in extracted_matches
                }),
                "statuses": sorted({
                    item["status"] for item in extracted_matches
                }),
            })
        allowed_categories = evidence_extractor.ROLE_CATEGORIES[name]
        expected_role_ids = {
            item["evidence_id"]
            for item in extraction["observations"]
            if item["category"] in allowed_categories
        }
        delivered_ids = {
            item["evidence_id"] for item in role_package["observations"]
        }
        raw_response, raw_response_truncated = llm_runtime._redact_diagnostic(
            raw_content, limit=12000
        )
        entry["deterministic_evidence"] = _safe_report_value(extraction)
        entry["evidence_delivery"] = {
            **_safe_report_value(role_package),
            "expected_role_observation_ids": sorted(expected_role_ids),
            "delivered_observation_ids": sorted(delivered_ids),
            "all_role_observations_delivered": expected_role_ids == delivered_ids,
            "excluded_irrelevant_observation_ids": sorted(
                item["evidence_id"]
                for item in extraction["observations"]
                if item["category"] not in allowed_categories
            ),
            "role_categories": sorted(allowed_categories),
        }
        entry["required_fact_results"] = required_results
        entry["extraction_completeness"] = (
            sum(item["extracted"] for item in required_results) / len(expected)
            if expected else 1.0
        )
        entry["delivery_completeness"] = (
            sum(item["delivered"] for item in required_results) / len(expected)
            if expected else 1.0
        )
        entry["unavailable_or_stale_evidence"] = {
            "stale_observations": [
                item for item in extraction["observations"]
                if item["status"] == "stale"
            ],
            "unavailable_or_invalid_sources": extraction["missing_evidence"],
            "status_counts": {
                status: sum(
                    item["status"] == status
                    for item in extraction["observations"]
                )
                for status in sorted(evidence_extractor.OBSERVATION_STATUSES)
            },
        }
        entry["raw_response_redacted"] = _safe_report_value(raw_response)
        entry["raw_response_truncated"] = raw_response_truncated
        entry["model_token_truncated"] = any(
            attempt.get("done_reason") == "length"
            for attempt in attempts if isinstance(attempt, dict)
        )
        entry["ollama_inference_seconds"] = sum(
            attempt.get("total_duration", 0) / 1e9
            for attempt in attempts
            if isinstance(attempt, dict)
            and isinstance(attempt.get("total_duration"), (int, float))
        )
        entry["response_categories"] = _categorize_response(
            analysis, claims, role_package["missing_evidence"]
        )
        entry["response_categories"]["verified_observations"] = (
            entry["evidence_delivery"]["observations"]
        )
    entry.update(_grade_agent(
        name,
        scenario,
        analysis if isinstance(analysis, dict) else None,
        claims,
        result_status,
        parse_valid,
        entry["model_mapping_matches"],
        entry["routing_selected"],
    ))
    return entry, end_perf


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    lines = [
        "# Six-Agent Live Ollama Evaluation",
        "",
        f"- **Run time (UTC):** {report['environment']['run_utc']}",
        f"- **Ollama URL:** `{report['environment']['ollama_url']}`",
        f"- **Ollama reachable:** {report['environment']['ollama_reachable']}",
        f"- **Python:** {report['environment']['python']}",
        f"- **GPU:** {report['environment']['gpu'].get('reported', report['environment']['gpu'].get('detail', 'unavailable'))}",
        f"- **Runtime limits:** `{json.dumps(report['environment']['runtime'], sort_keys=True)}`",
        f"- **Installed models:** {', '.join(report['environment']['installed_models']) or 'none'}",
        f"- **Inference execution:** sequential; overlap detected: {report['sequential_overlap_detected']}",
        "- **Evidence:** synthetic test fixtures only; no deployment, rollback, or remediation executed.",
        "",
        "## Results",
        "",
        "| Specialist | Assigned model | Available | Selected | Inference | JSON/schema | Grounding summary | Latency (s) | Retries | Result |",
        "|---|---|---:|---:|---|---|---|---:|---:|---|",
    ]
    for entry in report["agents"]:
        if entry.get("inference_status") == "skipped":
            lines.append(
                f"| {entry['agent']} | {entry['assigned_model']} | No | {entry.get('routing_selected', False)} | SKIPPED | — | Model not installed | — | 0 | SKIPPED |"
            )
            continue
        unsupported = sum(
            claim["classification"] in {
                "Unsupported or unverified claim",
                "Recommendation with unsupported premise",
            }
            for claim in entry.get("claims", [])
        )
        hypotheses = sum(
            claim["classification"] == "Reasonable hypothesis (unconfirmed)"
            for claim in entry.get("claims", [])
        )
        grounding = f"{unsupported} unverified; {hypotheses} hypotheses"
        result = entry.get("overall_result", "PARTIAL")
        lines.append(
            f"| {entry['agent']} | {entry['assigned_model']} | "
            f"{'Yes' if entry.get('model_available') else 'No'} | "
            f"{'Yes' if entry.get('routing_selected') else 'No'} | "
            f"{entry.get('inference_status', 'unknown')} | "
            f"{'Valid' if entry.get('json_schema_valid') else 'Invalid'} | "
            f"{grounding} | {entry.get('latency_seconds', 0):.2f} | "
            f"{entry.get('retry_count', 0)} | {result} |"
        )

    for entry in report["agents"]:
        lines.extend(["", f"## {entry['agent'].title()} — {entry.get('overall_result', 'SKIPPED')}", ""])
        lines.append(f"- **Scenario:** {entry.get('scenario_summary', 'Synthetic evidence scenario.')}")
        lines.append(f"- **Routing:** {'selected' if entry.get('routing_selected') else 'not selected'}; graph-selected agents: `{entry.get('routing_selected_agents', [])}`.")
        lines.append(f"- **Model mapping:** assigned `{entry['assigned_model']}`, response model `{entry.get('reported_model') or 'not invoked'}`.")
        lines.append(f"- **Inference:** `{entry.get('inference_status')}`; JSON/schema valid: `{entry.get('json_schema_valid')}`; latency: `{entry.get('latency_seconds', 0):.2f}s`; retries: `{entry.get('retry_count', 0)}`.")
        if entry.get("validation_error"):
            lines.append(f"- **Validation error:** {entry['validation_error']}")
        if entry.get("error_detail"):
            lines.append(f"- **Error/limitation:** {entry['error_detail']}")
        lines.extend(["", "### Expected evaluation criteria", ""])
        lines.extend(f"- {criterion}" for criterion in entry.get("expected_criteria", []))
        lines.extend(["", "### Parsed model response", "", "```json"])
        lines.append(json.dumps(entry.get("analysis"), indent=2, ensure_ascii=False))
        lines.extend(["```", "", "### Claim classifications (existing graph validator)", ""])
        if entry.get("claims"):
            for claim in entry["claims"]:
                refs = ", ".join(claim["evidence_refs"]) or "none"
                lines.append(
                    f"- **{claim['classification']}** ({claim['kind']}): "
                    f"{claim['text']} — evidence refs: `{refs}`"
                )
                if claim["reasons"]:
                    lines.append("  - Validator notes: " + "; ".join(claim["reasons"]))
        else:
            lines.append("No parsed claims were available.")
        lines.extend(["", "### Retry/diagnostic record", "", "```json"])
        lines.append(json.dumps({
            "retry": entry.get("retry"),
            "attempts": entry.get("attempts"),
            "raw_excerpt": entry.get("raw_excerpt"),
            "raw_excerpt_truncated": entry.get("raw_excerpt_truncated"),
        }, indent=2, ensure_ascii=False))
        lines.extend(["```"])

    lines.extend([
        "",
        "## Failure handling and limitations",
        "",
        "Offline runtime tests cover Ollama unavailable, malformed/truncated JSON, one correction retry, retry failure, strict schema failures, and invalid responses. The live harness did not stop Ollama or induce a live timeout/server failure. One specialist failure continuing through the graph is covered by offline graph tests; live inference here calls each runtime specialist sequentially rather than running remediation or the full interrupt/approval graph.",
        "",
        "Claim grounding uses the existing conservative `graph._validate_finding` function. It is not a general natural-language fact checker: unmatched numerical/unit claims and prose without recognized evidence links are reported unverified. A model's confidence is not proof. Synthetic fixture performance does not establish real-world diagnostic accuracy.",
        "",
        "Sequentiality was enforced by serial calls to `llm_runtime.analyze` plus its process-wide lock. Per-model start/end wall timestamps are recorded; no calls overlap. The runtime exposes total inference duration and request wall duration, but not Ollama load/unload duration fields. `/api/ps` was sampled before and after each inference; keep-alive is configured as `{}`.".format(report["environment"]["runtime"].get("keep_alive")),
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        if parts.port is not None:
            hostname = f"{hostname}:{parts.port}"
        return urlunsplit((parts.scheme, hostname, parts.path.rstrip("/"), "", ""))
    except ValueError:
        return "<invalid OLLAMA_HOST>"


def _safe_error_detail(value: Any) -> str | None:
    if value is None:
        return None
    text = llm_runtime._redact_sensitive_content(value)
    return re.sub(
        r"(?i)(https?://)[^/@\s]+@",
        r"\1[REDACTED]@",
        text,
    )


def _read_previous_baseline() -> dict[str, Any]:
    return json.loads(json.dumps(HISTORICAL_BASELINE))


def _write_grounding_report(report: dict[str, Any]) -> None:
    GROUNDING_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    GROUNDING_JSON_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    lines = [
        "# Six-Agent Evidence Grounding Evaluation",
        "",
        f"- **Run time (UTC):** {report['environment']['run_utc']}",
        f"- **Ollama endpoint:** `{report['environment']['ollama_url']}`",
        f"- **Models installed:** {', '.join(report['environment']['installed_models'])}",
        f"- **Sequential inference:** overlap detected: `{report['sequential_overlap_detected']}`",
        f"- **Total model inference:** {report['summary']['total_inference_seconds']:.2f} seconds",
        f"- **Offline suite:** `{report['offline_tests']['command']}` — {report['offline_tests']['summary']}",
        "- **Operational actions:** none; only synthetic fixtures were sent to Ollama.",
        "",
        "## Root-cause analysis",
        "",
        *[f"- {item}" for item in report["root_cause_analysis"]],
        "",
        "## Changes made",
        "",
        *[f"- `{item['file']}` — {item['change']}" for item in report["changes"]],
        "",
        "## Six-agent evaluation",
        "",
        "| Specialist | Model | Inference | Schema | Evidence criteria | Material unsupported claims | Latency (s) | Retries | Result |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for entry in report["agents"]:
        passed = sum(
            item["identified"] for item in entry.get("required_observations", [])
        )
        total = len(entry.get("required_observations", []))
        lines.append(
            f"| {entry['agent']} | {entry.get('assigned_model', '—')} | "
            f"{entry.get('inference_status', 'skipped')} | "
            f"{'valid' if entry.get('json_schema_valid') else 'invalid'} | "
            f"{passed}/{total} | {len(entry.get('material_unsupported_claims', []))} | "
            f"{entry.get('latency_seconds', 0):.2f} | "
            f"{entry.get('retry_count', 0)} | {entry.get('overall_result', 'SKIPPED')} |"
        )
    lines.extend(["", "## Before versus after", ""])
    baseline = report.get("baseline")
    if baseline:
        lines.append(
            f"- **Prior run:** {baseline.get('run_utc')}; "
            f"{baseline.get('summary', {}).get('inference_ok', 0)} inference successes, "
            f"{baseline.get('summary', {}).get('schema_valid', 0)} schema-valid responses."
        )
        lines.append(f"- **Prior rubric note:** {baseline['interpretation']}")
        previous_agents = {
            entry["agent"]: entry for entry in baseline.get("agents", [])
        }
        lines.extend([
            "",
            "| Specialist | Prior model | Prior result | Prior latency (s) | Current model | Current result | Current latency (s) |",
            "|---|---|---|---:|---|---|---:|",
        ])
        for entry in report["agents"]:
            previous = previous_agents.get(entry["agent"], {})
            previous_latency = previous.get("latency_seconds")
            current_latency = entry.get("latency_seconds")
            previous_latency_text = (
                f"{previous_latency:.2f}"
                if isinstance(previous_latency, (int, float))
                else "—"
            )
            current_latency_text = (
                f"{current_latency:.2f}"
                if isinstance(current_latency, (int, float))
                else "—"
            )
            lines.append(
                f"| {entry['agent']} | {previous.get('model', '—')} | "
                f"{previous.get('reported_result', '—')} | "
                f"{previous_latency_text} | {entry.get('assigned_model', '—')} | "
                f"{entry.get('overall_result', 'SKIPPED')} | {current_latency_text} |"
            )
    else:
        lines.append("- No previous live evaluation report was available.")
    lines.append(
        f"- **Current run:** {report['summary']['inference_ok']} inference successes, "
        f"{report['summary']['schema_valid']} schema-valid responses; "
        f"{report['summary']['pass']} PASS, {report['summary']['partial']} PARTIAL, "
        f"{report['summary']['failed']} FAIL, {report['summary']['skipped']} SKIPPED."
    )
    lines.extend([
        "",
        "The prior run's synthetic evidence had been manually translated into graph "
        "state, included unrelated unavailable-source placeholders, and the harness "
        "did not grade its stated acceptance criteria. Baseline labels therefore "
        "cannot be used as evidence of improvement. The current report records both "
        "the original synthetic fixture and the final shaped evidence/prompt for "
        "each model so evidence-flow differences are inspectable.",
        "",
        "## Limitations",
        "",
        "- Offline tests use mocks and do not establish live model behavior.",
        "- Live calls evaluate synthetic fixtures only, not a real incident or production telemetry.",
        "- Anchor checks are explicit regression checks, not a general natural-language reasoning benchmark.",
        "- The existing finding validator is conservative and does not prove semantic truth.",
        "- LLM recommendations remain advisory; no deployment, rollback, or remediation ran.",
        "",
        "## Configuration and safety",
        "",
        f"- Persistent `config/models.json` SHA-256 unchanged: `{report['safety']['model_config_unchanged']}`.",
        f"- Persistent LLM configuration enabled: `{report['safety']['persistent_config_enabled']}`.",
        f"- Runtime `max_parallel_models`: `{report['environment']['runtime'].get('max_parallel_models')}`.",
        f"- `keep_alive`: `{report['environment']['runtime'].get('keep_alive')}`.",
        f"- Ollama had models loaded after the run: `{report['safety']['models_loaded_after_run']}`.",
        "- No model mappings or persistent enablement settings were changed.",
        "",
        "Per-agent original evidence, shaped evidence, exact sanitized prompts, model "
        "outputs, claim validation, and truncation/size measurements are in the "
        "companion JSON report.",
        "",
    ])
    GROUNDING_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _parse_pytest_summary(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    summary_line = next(
        (
            line
            for line in reversed(output.splitlines())
            if re.search(r"\b\d+\s+(?:passed|failed|skipped)\b", line)
        ),
        None,
    )
    if summary_line is None:
        raise ValueError("Pytest completed without a parseable summary line.")
    for match in re.finditer(r"\b(\d+)\s+(passed|failed|skipped)\b", summary_line):
        counts[match.group(2)] += int(match.group(1))
    return counts


def run_evaluation() -> dict[str, Any]:
    previous_baseline = _read_previous_baseline()
    model_config_path = ROOT / "config" / "models.json"
    model_config_hash_before = hashlib.sha256(model_config_path.read_bytes()).hexdigest()
    cfg = llm_runtime.load_config()
    installed, missing, base_url = _expected_installed_tags()
    cfg["_installed_models"] = installed
    scenarios = _scenario_data()
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    test_output = test_result.stdout + test_result.stderr
    if test_result.returncode != 0:
        raise RuntimeError(
            "Offline pytest suite failed; live inference was not started.\n"
            + test_output[-4000:]
        )
    test_counts = _parse_pytest_summary(test_output)
    offline_tests = {
        "command": "python -m pytest -q",
        "return_code": test_result.returncode,
        "counts": test_counts,
        "summary": (
            f"{test_counts['passed']} passed, {test_counts['failed']} failed, "
            f"{test_counts['skipped']} skipped"
        ),
    }
    api_version = None
    try:
        response = requests.get(base_url + "/api/version", timeout=5)
        response.raise_for_status()
        api_version = response.json().get("version")
        reachable = True
    except (requests.RequestException, ValueError, TypeError):
        reachable = False
    initial_processes = _ollama_processes(base_url) if reachable else None
    loaded_before = (
        initial_processes.get("models", [])
        if isinstance(initial_processes, dict)
        else None
    )
    preflight_error = (
        initial_processes.get("error")
        if isinstance(initial_processes, dict)
        else "Ollama process inventory is unavailable."
    )
    safe_base_url = _safe_url(base_url)
    can_infer = (
        reachable
        and not missing
        and loaded_before == []
        and preflight_error is None
    )

    environment = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "ollama_url": safe_base_url,
        "ollama_reachable": reachable,
        "ollama_version": api_version,
        "installed_models": installed,
        "missing_models": missing,
        "python": platform.python_version(),
        "gpu": _gpu_info(),
        "runtime": cfg.get("runtime", {}),
        "llm_enabled_process_override": os.getenv("DEVOPS_LLM_ENABLED") == "true",
        "persistent_config_enabled": json.loads(
            model_config_path.read_text(encoding="utf-8")
        ).get("enabled"),
        "ollama_processes_before": initial_processes,
    }
    entries = []
    previous_end = None
    overlap_detected = False
    for name in AGENT_ORDER:
        if not can_infer:
            entries.append({
                "agent": name,
                "assigned_model": EXPECTED_MODELS[name],
                "model_available": name not in missing,
                "inference_status": "skipped",
                "routing_selected": False,
                "overall_result": "SKIPPED",
                "scenario_summary": (
                    "Not run because Ollama, an assigned model, or the unloaded-model "
                    f"preflight was unavailable: {preflight_error or ', '.join(missing) or 'models already loaded'}."
                ),
                "expected_criteria": scenarios[name]["expected_criteria"],
            })
            continue
        entry, previous_end = _evaluate_one(
            name, scenarios[name], cfg, base_url, previous_end
        )
        entry["scenario_summary"] = scenarios[name]["task"]
        overlap_detected = overlap_detected or not entry["no_overlap_with_previous"]
        entries.append(entry)

    model_config_hash_after = hashlib.sha256(model_config_path.read_bytes()).hexdigest()
    processes_after = _ollama_processes(base_url) if reachable else None
    total_inference_seconds = sum(
        attempt.get("total_duration", 0) / 1e9
        for entry in entries
        for attempt in entry.get("attempts", [])
        if isinstance(attempt.get("total_duration"), (int, float))
    )
    report = {
        "environment": environment,
        "sequential_overlap_detected": overlap_detected,
        "agents": entries,
        "summary": {
            "total": len(entries),
            "inference_ok": sum(item.get("inference_status") == "ok" for item in entries),
            "schema_valid": sum(item.get("json_schema_valid") is True for item in entries),
            "skipped": sum(item.get("inference_status") == "skipped" for item in entries),
            "failed": sum(item.get("overall_result") == "FAIL" for item in entries),
            "pass": sum(item.get("overall_result") == "PASS" for item in entries),
            "partial": sum(item.get("overall_result") == "PARTIAL" for item in entries),
            "total_inference_seconds": total_inference_seconds,
            "total_wall_seconds": sum(
                item.get("latency_seconds", 0)
                for item in entries
                if isinstance(item.get("latency_seconds"), (int, float))
            ),
        },
    }
    _write_report(report)
    improvement_report = {
        "environment": environment,
        "offline_tests": offline_tests,
        "baseline": previous_baseline,
        "root_cause_analysis": [
            "The previous live harness hand-translated synthetic fixtures into graph state and inserted generic unavailable-source placeholders. This did not match the production evidence contract and let unrelated missing-source text distract from supplied observations.",
            "The shared prompt requested citations but did not require a fixed observations-first pass or say that an unavailable source must not override another source's valid measurements.",
            "Graph evidence shaping sent broad bundles to multiple specialists; code evaluation bypassed graph shaping, while the other routes received irrelevant health, deployment, logs, or source-availability fields.",
            "The prior harness did not evaluate its stated acceptance criteria and assigned PARTIAL to every successful response. Its status labels were therefore not a content-quality comparison.",
            "The claim validator accepted security terms found in any evidence string, including negative telemetry details, and did not verify recommendation premises. Its numeric aliases also missed several observed units and Prometheus query-value paths.",
            "The monitoring fixture initially placed Prometheus rates in application counter fields, creating a false cumulative-total observation; the corrected fixture now keeps those independent sources separate.",
            "The offline pytest summary parser previously matched an all-optional empty pattern, reporting zero tests despite a passing suite; it now extracts actual passed/failed/skipped counts and rejects missing summaries.",
            "Validation also needed to recognize underscore-separated Prometheus names, scientific notation, percentile labels, punctuated IPv4 addresses, and container IDs without confusing them for container names.",
        ],
        "changes": [
            {
                "file": "agents/graph.py",
                "change": "Scope specialist evidence by role, route CI/CD pipeline availability, add source-path observations, and validate Prometheus metrics, availability claims, container IDs, and recommendations against original source evidence.",
            },
            {
                "file": "agents/llm_runtime.py",
                "change": "Use an observations-first reasoning contract that directs specialists to retain exact source paths and timestamps without changing the JSON schema, model mappings, limits, retries, or sequential lock.",
            },
            {
                "file": "tests/live_agent_evaluation.py",
                "change": "Use production-shaped independent telemetry fixtures, preserve source/shaped evidence and sanitized prompts, record prompt sizes, grade explicit criteria, and parse pytest summaries strictly.",
            },
            {
                "file": "tests/test_graph.py",
                "change": "Add regressions for role-scoped evidence, source-path observation indexing, and unsupported source-availability/security claims and recommendation premises.",
            },
            {
                "file": "tests/test_llm_runtime.py",
                "change": "Test the shared evidence-first prompt, deterministic observation-index guidance, and independent source handling.",
            },
            {
                "file": "tests/test_telemetry.py",
                "change": "Update Security evidence-routing expectations to include the deterministic observation index.",
            },
            {
                "file": "tests/test_live_agent_evaluation.py",
                "change": "Test scenario grading and credential-safe diagnostics/report generation offline.",
            },
            {
                "file": "reports/six_agent_grounding_improvement.md and .json",
                "change": "Record the before/after synthetic evaluation, exact sanitized prompts, evidence payloads, and validation details.",
            },
        ],
        "sequential_overlap_detected": overlap_detected,
        "agents": entries,
        "summary": report["summary"],
        "safety": {
            "model_config_sha256_before": model_config_hash_before,
            "model_config_sha256_after": model_config_hash_after,
            "model_config_unchanged": model_config_hash_before == model_config_hash_after,
            "persistent_config_enabled": environment["persistent_config_enabled"],
            "models_loaded_before_run": len(loaded_before) if isinstance(loaded_before, list) else None,
            "models_loaded_after_run": (
                len(processes_after.get("models", []))
                if isinstance(processes_after, dict)
                and isinstance(processes_after.get("models"), list)
                else None
            ),
            "remediation_executed": False,
            "deployment_executed": False,
            "rollback_executed": False,
        },
    }
    _write_grounding_report(improvement_report)
    return improvement_report


PROMPT7_REQUIRED_FACTS = {
    "monitoring": [
        ("application_metrics", "request_rate", None),
        ("application_metrics", "http_error_rate", None),
        ("application_metrics", "latency_p95", None),
        ("application_metrics", "cpu_utilization", None),
        ("application_metrics", "memory_usage", None),
    ],
    "incident": [
        ("deployment", "previous_application_version", None),
        ("deployment", "current_application_version", None),
        ("application_metrics", "div_error_request_count", None),
        ("application_metrics", "div_p95_latency", None),
        ("application_log", "application_log_event", "timeout"),
    ],
    "code": [
        ("code", "source_code", None),
        ("code", "error_message", None),
        ("code", "stack_trace", None),
    ],
    "cicd": [
        ("deployment", "previous_application_version", None),
        ("deployment", "current_application_version", None),
        ("deployment", "deployment_status", None),
        ("deployment", "health_status", None),
        ("deployment", "health_http_status", None),
        ("application_metrics", "error_rate", None),
    ],
    "infrastructure": [
        ("infrastructure", "container_name", None),
        ("infrastructure", "container_status", None),
        ("infrastructure", "container_health_status", None),
        ("infrastructure", "container_restart_count", None),
        ("infrastructure", "container_cpu_usage_percent", None),
        ("infrastructure", "container_memory_usage_bytes", None),
        ("infrastructure", "host_process_memory_mib", None),
    ],
    "security": [
        ("security", "authentication_failure", None),
        ("security", "authentication_success", None),
        ("security", "source_ip", None),
        ("security", "repeated_failures_followed_by_success", None),
    ],
}


def _required_fact_matches(
    observations: list[dict[str, Any]],
    requirement,
    *,
    include_stale: bool = False,
):
    category, metric_or_event, text_match = requirement
    valid_statuses = {"observed", "derived", "partial"}
    if include_stale:
        valid_statuses.add("stale")
    return [
        item for item in observations
        if item.get("category") == category
        and item.get("metric_or_event") == metric_or_event
        and item.get("status") in valid_statuses
        and (
            text_match is None
            or text_match.lower() in str(item.get("evidence_text", "")).lower()
        )
    ]


def _previous_live_snapshot() -> dict[str, Any]:
    try:
        report = json.loads(JSON_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "agents": [], "run_utc": None}
    return {
        "available": True,
        "run_utc": report.get("environment", {}).get("run_utc"),
        "summary": report.get("summary", {}),
        "agents": [
            {
                "agent": entry.get("agent"),
                "model": entry.get("assigned_model"),
                "result": entry.get("overall_result"),
                "inference_status": entry.get("inference_status"),
                "schema_valid": entry.get("json_schema_valid"),
                "missing_observations": entry.get("missing_observations", []),
                "unsupported_claims": entry.get("material_unsupported_claims", []),
                "latency_seconds": entry.get("latency_seconds"),
            }
            for entry in report.get("agents", [])
            if isinstance(entry, dict)
        ],
    }


def _build_prompt7_offline_report(
    offline_tests: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate extraction and routing only; this function never calls an LLM."""
    scenarios = _scenario_data()
    previous_live = _previous_live_snapshot()
    config = llm_runtime.load_config()
    agents = []
    extracted_total = delivered_total = required_total = 0
    for name in AGENT_ORDER:
        scenario = scenarios[name]
        state = _routing_state(name, scenario)
        state.setdefault("baseline", {"status": "unavailable"})
        extraction = evidence_extractor.validate_extraction(
            evidence_extractor.extract_evidence(
                state["evidence"],
                state["baseline"],
                state["comparison"],
            )
        )
        shaped = graph._specialist_evidence(name, state)
        package = evidence_extractor.package_for_role(
            extraction, name, raw_evidence=state["evidence"]
        )
        expected = PROMPT7_REQUIRED_FACTS[name]
        extracted_requirements = []
        delivered_requirements = []
        missing_facts = []
        for category, metric, text_match in expected:
            matches = _required_fact_matches(extraction["observations"], (
                category, metric, text_match,
            ))
            delivered = _required_fact_matches(package["observations"], (
                category, metric, text_match,
            ))
            extracted = bool(matches)
            delivered_ok = bool(delivered)
            required_total += 1
            extracted_total += int(extracted)
            delivered_total += int(delivered_ok)
            fact_result = {
                "category": category,
                "metric_or_event": metric,
                "evidence_text_contains": text_match,
                "extracted": extracted,
                "delivered": delivered_ok,
                "evidence_ids": [item["evidence_id"] for item in matches],
                "delivered_evidence_ids": [
                    item["evidence_id"] for item in delivered
                ],
                "source_paths": sorted({
                    item["source_path"] for item in matches
                }),
            }
            extracted_requirements.append(fact_result)
            delivered_requirements.append(fact_result)
            if not extracted:
                missing_facts.append(f"{category}.{metric}")
        role_observations = package["observations"]
        role_categories = evidence_extractor.ROLE_CATEGORIES[name]
        expected_role_observations = [
            item for item in extraction["observations"]
            if item["category"] in role_categories
        ]
        delivered_ids = {item["evidence_id"] for item in role_observations}
        source_ids = {item["evidence_id"] for item in expected_role_observations}
        delivery_complete = delivered_ids == source_ids
        model_baseline = next(
            (
                item for item in previous_live["agents"]
                if item["agent"] == name
            ),
            {},
        )
        agents.append({
            "agent": name,
            "model": EXPECTED_MODELS[name],
            "scenario": scenario["task"],
            "scenario_requirements": [
                item["requirement"]
                for item in _required_observations(name, scenario)
            ],
            "extraction_status": extraction["status"],
            "extracted_observation_count": len(extraction["observations"]),
            "role_observation_count": len(role_observations),
            "required_fact_count": len(expected),
            "required_facts_extracted": sum(
                item["extracted"] for item in extracted_requirements
            ),
            "required_facts_delivered": sum(
                item["delivered"] for item in delivered_requirements
            ),
            "extraction_completeness": (
                sum(item["extracted"] for item in extracted_requirements) / len(expected)
                if expected else 1.0
            ),
            "delivery_completeness": (
                sum(item["delivered"] for item in delivered_requirements) / len(expected)
                if expected else 1.0
            ),
            "all_extracted_role_evidence_delivered": delivery_complete,
            "extraction_requirements": extracted_requirements,
            "delivery_requirements": delivered_requirements,
            "missing_required_facts": missing_facts,
            "missing_source_evidence": package["missing_evidence"],
            "verified_observations": role_observations,
            "interpretation": {
                "status": "not_run",
                "schema_valid": None,
                "complete": None,
                "unsupported_claims": [],
                "reason": "Live Ollama inference was explicitly deferred.",
            },
            "prior_live_result": model_baseline,
            "current_result": "NOT_RUN",
            "routing_selected": name in graph._select_specialists(state),
            "evidence_payload_matches_graph": (
                shaped["deterministic_evidence"]["observations"] == role_observations
            ),
        })

    mappings = {
        name: llm_runtime.model_for(name, config)
        for name in AGENT_ORDER
    }
    return {
        "report_version": 1,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "offline deterministic evaluation; no Ollama calls",
        "architecture": [
            "Collected evidence remains unchanged and accessible.",
            "A strict deterministic extractor records source-traceable observations.",
            "Role packaging filters observations before the specialist request.",
            "Specialist results preserve extracted facts independently of model output.",
            "RCA separates verified observations, interpretations, hypotheses, recommendations, and unverified claims.",
        ],
        "previous_live_run": previous_live,
        "root_cause_analysis": [
            {
                "agent": item["agent"],
                "prior_result": item["prior_live_result"].get("result"),
                "missing_facts": item["prior_live_result"].get(
                    "missing_observations", []
                ),
                "unsupported_claims": [
                    claim.get("text")
                    for claim in item["prior_live_result"].get(
                        "unsupported_claims", []
                    )
                    if isinstance(claim, dict)
                ],
            }
            for item in agents
            if item["prior_live_result"].get("result") == "PARTIAL"
        ],
        "agents": agents,
        "summary": {
            "agents_total": len(agents),
            "agents_pass_extraction_delivery": sum(
                not item["missing_required_facts"]
                and item["all_extracted_role_evidence_delivered"]
                for item in agents
            ),
            "agents_partial_extraction_delivery": sum(
                bool(item["missing_required_facts"])
                or not item["all_extracted_role_evidence_delivered"]
                for item in agents
            ),
            "agents_failed_extraction_delivery": 0,
            "required_facts_total": required_total,
            "required_facts_extracted": extracted_total,
            "required_facts_delivered": delivered_total,
            "evidence_extraction_success_rate": (
                extracted_total / required_total if required_total else 1.0
            ),
            "evidence_delivery_success_rate": (
                delivered_total / required_total if required_total else 1.0
            ),
            "interpretation_completeness_rate": None,
            "interpretation_evaluated_agents": 0,
            "live_model_inference": "not_run",
        },
        "offline_tests": offline_tests,
        "model_mappings": mappings,
        "safety": {
            "persistent_model_config_enabled": json.loads(
                (ROOT / "config" / "models.json").read_text(encoding="utf-8")
            ).get("enabled"),
            "effective_model_config_enabled": config.get("enabled"),
            "max_parallel_models": config.get("runtime", {}).get(
                "max_parallel_models"
            ),
            "live_inference_executed": False,
            "remediation_executed": False,
            "rollback_executed": False,
        },
        "limitations": [
            "This report validates deterministic extraction and role delivery only; model interpretation completeness is not evaluated because live inference was not run.",
            "Derived error rates are computed only when observed successful/error counters provide a non-zero denominator.",
            "A suspicious authentication sequence is a deterministic sequence description, not a threat classification or proof of compromise.",
        ],
    }


def _write_prompt7_reports(report: dict[str, Any]) -> None:
    PROMPT7_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT7_JSON_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    summary = report["summary"]
    lines = [
        "# Prompt 7.0 — Deterministic Evidence Extraction",
        "",
        f"- **Generated (UTC):** {report['run_utc']}",
        f"- **Execution:** {report['execution_mode']}",
        f"- **Offline tests:** {report['offline_tests']['summary']}",
        "- **Live Ollama inference:** not run, as requested.",
        "- **Operational actions:** no deployment, rollback, or remediation executed.",
        "",
        "## Previous live evaluation: observed causes of PARTIAL results",
        "",
        "This analysis uses the latest persisted live-evaluation JSON. It records model omissions and validator findings from that run; it does not treat the old model response as verified evidence.",
    ]
    for item in report["root_cause_analysis"]:
        missing = ", ".join(item["missing_facts"]) or "none recorded"
        unsupported_count = len(item["unsupported_claims"])
        lines.append(
            f"- **{item['agent']} ({item['prior_result']}):** "
            f"missing response criteria: {missing}; "
            f"unsupported-claim findings: {unsupported_count}."
        )
    lines.extend([
        "",
        "## Deterministic extraction and role delivery",
        "",
        "| Specialist | Model | Extracted required facts | Delivered required facts | Delivery complete | Prior result | Current interpretation |",
        "|---|---|---:|---:|---|---|---|",
    ])
    for item in report["agents"]:
        lines.append(
            f"| {item['agent']} | {item['model']} | "
            f"{item['required_facts_extracted']}/{item['required_fact_count']} | "
            f"{item['required_facts_delivered']}/{item['required_fact_count']} | "
            f"{item['all_extracted_role_evidence_delivered']} | "
            f"{item['prior_live_result'].get('result', 'not available')} | NOT RUN |"
        )
    lines.extend([
        "",
        "## Aggregate results",
        "",
        f"- Agents evaluated: {summary['agents_total']}",
        f"- Extraction/delivery complete: {summary['agents_pass_extraction_delivery']}",
        f"- Extraction/delivery partial: {summary['agents_partial_extraction_delivery']}",
        f"- Required facts extracted: {summary['required_facts_extracted']}/{summary['required_facts_total']} ({summary['evidence_extraction_success_rate']:.1%})",
        f"- Required facts delivered: {summary['required_facts_delivered']}/{summary['required_facts_total']} ({summary['evidence_delivery_success_rate']:.1%})",
        "- Interpretation completeness: not measured; live inference was not run.",
        "",
        "## Architecture and safety",
        "",
        *[f"- {item}" for item in report["architecture"]],
        "",
        f"- Persisted model enablement: `{report['safety']['persistent_model_config_enabled']}`.",
        f"- `max_parallel_models`: `{report['safety']['max_parallel_models']}`.",
        f"- Model mappings: `{json.dumps(report['model_mappings'], sort_keys=True)}`.",
        "- Source values, timestamps, units, and paths are preserved in JSON. Stale/unavailable/invalid values remain explicitly marked.",
        "- Verified observations are kept separate from LLM interpretations and cannot be overwritten by specialist output.",
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
        "The companion JSON contains per-fact extraction and delivery results, source paths, missing-source records, prior model-result diagnostics, model mapping, and safety settings.",
        "",
    ])
    PROMPT7_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _prompt6_scenarios_from_report() -> dict[str, dict[str, Any]]:
    """Rehydrate the exact synthetic evidence and task saved by Prompt 6.0."""
    report = json.loads(JSON_REPORT_PATH.read_text(encoding="utf-8"))
    current_definitions = _scenario_data()
    entries = {
        entry.get("agent"): entry
        for entry in report.get("agents", [])
        if isinstance(entry, dict)
    }
    scenarios = {}
    for name in AGENT_ORDER:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"Prompt 6.0 report has no {name} scenario")
        evidence = entry.get("original_synthetic_evidence")
        task = entry.get("scenario_summary")
        criteria = entry.get("expected_criteria")
        if (
            not isinstance(evidence, dict)
            or not isinstance(task, str)
            or not isinstance(criteria, list)
            or not all(isinstance(item, str) for item in criteria)
        ):
            raise ValueError(
                f"Prompt 6.0 scenario for {name} is incomplete; "
                "cannot guarantee identical evaluation inputs"
            )
        scenarios[name] = {
            "task": task,
            "query": current_definitions[name]["query"],
            "comparison": current_definitions[name]["comparison"],
            "evidence": evidence,
            "expected_criteria": criteria,
        }
    return scenarios


def _prompt6_grounding_results() -> dict[str, Any]:
    report = json.loads(GROUNDING_JSON_PATH.read_text(encoding="utf-8"))
    agents = {
        entry.get("agent"): entry
        for entry in report.get("agents", [])
        if isinstance(entry, dict)
    }
    if set(agents) != set(AGENT_ORDER):
        raise ValueError("Prompt 6.0 grounding report must include all six agents")
    return report


def _claim_counts(entry: dict[str, Any]) -> tuple[int, int]:
    claims = entry.get("claims", [])
    unsupported = entry.get("material_unsupported_claims", [])
    if not isinstance(claims, list) or not isinstance(unsupported, list):
        return 0, len(unsupported) if isinstance(unsupported, list) else 0
    return len(claims), len(unsupported)


def _grounding_score(entry: dict[str, Any]) -> float | None:
    total, unsupported = _claim_counts(entry)
    if total == 0:
        return None
    return max(0.0, 1.0 - unsupported / total)


def _interpretation_score(entry: dict[str, Any]) -> tuple[int, int, float | None]:
    observations = entry.get("required_observations", [])
    if not isinstance(observations, list):
        return 0, 0, None
    matched = sum(
        bool(item.get("identified"))
        for item in observations if isinstance(item, dict)
    )
    total = sum(isinstance(item, dict) for item in observations)
    return matched, total, matched / total if total else None


def _categorize_response(
    analysis: Any,
    claims: list[dict[str, Any]],
    missing_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    interpretations = []
    hypotheses = []
    unverified = []
    recommendations = []
    if isinstance(analysis, dict):
        for key in ("summary", "findings"):
            values = [analysis.get(key)] if key == "summary" else analysis.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                if re.search(
                    r"\b(hypothes(?:is|ized)|possible|possibly|may|might|could|"
                    r"potential(?:ly)?)\b",
                    value,
                    re.IGNORECASE,
                ):
                    hypotheses.append(_safe_report_value(value))
                else:
                    interpretations.append(_safe_report_value(value))
        checks = analysis.get("recommended_checks", [])
        if isinstance(checks, list):
            recommendations = [
                _safe_report_value(item)
                for item in checks if isinstance(item, str)
            ]
    for claim in claims:
        if (
            claim.get("validation_status") == "unverified"
            or claim.get("reasons")
        ):
            unverified.append(claim)
    return {
        "verified_observations": [],
        "verified_observation_source": (
            "deterministic_evidence.observations only; model text is never "
            "promoted to verified evidence"
        ),
        "model_interpretations": interpretations,
        "hypotheses": hypotheses,
        "recommendations_not_executed": recommendations,
        "unverified_claims": unverified,
        "reported_missing_evidence": [
            _safe_report_value(item.get("detail", item.get("source_path")))
            for item in missing_evidence if isinstance(item, dict)
        ],
        "model_mentions_insufficient_evidence": [
            text for text in interpretations + hypotheses
            if re.search(r"\b(insufficient|unavailable|missing evidence)\b", text, re.I)
        ],
        "hypothesis_promoted_to_verified": False,
    }


PROMPT71_CRITERION_FACTS = {
    "monitoring": {
        "Successful request rate": [("application_metrics", "request_rate")],
        "Error request rate": [("application_metrics", "request_rate")],
        "Error rate": [("application_metrics", "http_error_rate")],
        "P95 latency": [("application_metrics", "latency_p95")],
        "Process CPU": [("application_metrics", "cpu_utilization")],
        "Process memory": [("application_metrics", "memory_usage")],
    },
    "incident": {
        "Previous version": [("deployment", "previous_application_version")],
        "Current version": [("deployment", "current_application_version")],
        "Previous error count": [("application_metrics", "div_error_counter_change")],
        "Current error count": [("application_metrics", "div_error_request_count")],
        "Baseline latency": [("application_metrics", "div_p95_latency")],
        "Current latency": [("application_metrics", "div_p95_latency")],
        "Timeout log evidence": [("application_log", "application_log_event")],
    },
    "code": {
        "Supplied function": [("code", "source_code")],
        "Empty input edge case": [("code", "error_message")],
        "Division failure": [("code", "error_message")],
    },
    "cicd": {
        "Previous version": [("deployment", "previous_application_version")],
        "Current version": [("deployment", "current_application_version")],
        "Deployment completion": [("deployment", "deployment_status")],
        "Health response": [
            ("deployment", "health_status"),
            ("deployment", "health_http_status"),
        ],
        "Post-deployment error rate": [
            ("application_metrics", "error_rate"),
        ],
    },
    "infrastructure": {
        "Container name": [("infrastructure", "container_name")],
        "Running state": [("infrastructure", "container_status")],
        "Healthy state": [("infrastructure", "container_health_status")],
        "Zero restarts": [("infrastructure", "container_restart_count")],
        "Container CPU": [("infrastructure", "container_cpu_usage_percent")],
        "Container memory": [("infrastructure", "container_memory_usage_bytes")],
        "Process memory": [("infrastructure", "host_process_memory_mib")],
    },
    "security": {
        "Synthetic source IP": [("security", "source_ip")],
        "Repeated failed logins": [
            ("security", "authentication_failure"),
            ("security", "repeated_failures_followed_by_success"),
        ],
        "Subsequent successful login": [
            ("security", "authentication_success"),
        ],
    },
}


def _prompt71_failure_analysis(
    entry: dict[str, Any],
    baseline_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    missing = entry.get("missing_observations", [])
    if entry.get("overall_result") not in {"PARTIAL", "FAIL"}:
        return []
    extracted = entry.get("deterministic_evidence", {}).get("observations", [])
    delivered = entry.get("evidence_delivery", {}).get("observations", [])
    requirement_map = PROMPT71_CRITERION_FACTS.get(entry.get("agent"), {})
    diagnostics = []
    for criterion in missing:
        mapped = requirement_map.get(criterion, [])
        extracted_facts = [
            fact for fact in extracted
            if (fact.get("category"), fact.get("metric_or_event")) in mapped
        ]
        delivered_facts = [
            fact for fact in delivered
            if (fact.get("category"), fact.get("metric_or_event")) in mapped
        ]
        raw_evidence_paths = []
        if criterion in {"Baseline latency", "Current latency"}:
            comparison = entry.get("graph_shaped_evidence", {}).get(
                "baseline_comparison", {}
            )
            deltas = comparison.get("latency_observation_deltas", {})
            if "div" in deltas:
                raw_evidence_paths.append(
                    "baseline_comparison.latency_observation_deltas.div"
                )
        diagnostics.append({
            "missed_model_criterion": criterion,
            "candidate_deterministic_facts": mapped,
            "facts_extracted": _safe_report_value(extracted_facts),
            "facts_delivered": _safe_report_value(delivered_facts),
            "facts_extracted_and_delivered": bool(extracted_facts)
            and bool(delivered_facts),
            "related_raw_evidence_paths": raw_evidence_paths,
            "interpretation": (
                "The response grader missed this criterion. When matching "
                "deterministic evidence was delivered, this is a model omission "
                "under the rubric; otherwise the extractor/packaging did not "
                "provide a corresponding fact. The raw response is preserved for "
                "review; this does not assert an unverified semantic contradiction."
            ),
        })
    if entry.get("material_unsupported_claims"):
        diagnostics.append({
            "validator_findings": entry["material_unsupported_claims"],
            "baseline_comparison": baseline_entry.get(
                "material_unsupported_claims", []
            ),
            "interpretation": (
                "The current validator marked these claims materially unsupported. "
                "The report preserves the exact reason and source evidence; it does "
                "not label a finding a false positive without independent evidence."
            ),
        })
    return diagnostics


def _prompt71_manual_review(report: dict[str, Any]) -> dict[str, Any]:
    """Annotate captured outputs; preserve the automated scores unchanged."""
    prompt6_by_agent = {
        item["agent"]: item
        for item in report["comparison"]["prompt6_agents"]
    }
    prompt7_by_agent = {item["agent"]: item for item in report["agents"]}
    prompt6_matches = {
        "monitoring": {
            "Successful request rate", "Error request rate", "Error rate",
            "P95 latency", "Process CPU", "Process memory",
        },
        "incident": set(),
        "code": {
            "Supplied function", "Empty input edge case", "Division failure",
        },
        "cicd": {"Deployment completion", "Health response"},
        "infrastructure": {
            "Container name", "Running state", "Container CPU",
            "Container memory", "Process memory",
        },
        "security": {
            "Synthetic source IP", "Repeated failed logins",
            "Subsequent successful login",
        },
    }
    prompt7_matches = {
        "monitoring": set(),
        "incident": set(),
        "code": {"Empty input edge case"},
        "cicd": set(),
        "infrastructure": {
            "Zero restarts", "Container CPU", "Container memory",
            "Process memory",
        },
        "security": {
            "Synthetic source IP", "Repeated failed logins",
            "Subsequent successful login",
        },
    }
    security_scenario = report.get("scenarios", {}).get("security", {})
    security_events = security_scenario.get(
        "original_synthetic_evidence", {}
    ).get("logs", {}).get("events", [])
    if isinstance(security_events, list) and len(security_events) >= 4:
        for event_index in (2, 3):
            event = security_events[event_index]
            if isinstance(event, dict) and isinstance(event.get("ts"), str):
                prompt6_matches["security"].add(
                    f"Event timestamp {event['ts']}"
                )
                prompt7_matches["security"].add(
                    f"Event timestamp {event['ts']}"
                )
    reviews = []
    for name in AGENT_ORDER:
        old = prompt6_by_agent[name]
        current = prompt7_by_agent[name]
        old_criteria = [
            item.get("requirement")
            for item in old.get("required_observations", [])
            if isinstance(item, dict)
        ]
        new_criteria = [
            item.get("requirement")
            for item in current.get("required_observations", [])
            if isinstance(item, dict)
        ]
        old_matched = [
            criterion for criterion in old_criteria
            if criterion in prompt6_matches[name]
        ]
        new_matched = [
            criterion for criterion in new_criteria
            if criterion in prompt7_matches[name]
        ]
        reviews.append({
            "agent": name,
            "prompt6_manual_matched": old_matched,
            "prompt6_manual_missed": [
                name for name in old_criteria if name not in old_matched
            ],
            "prompt6_manual_score": (
                len(old_matched) / len(old_criteria) if old_criteria else None
            ),
            "prompt7_manual_matched": new_matched,
            "prompt7_manual_missed": [
                name for name in new_criteria if name not in new_matched
            ],
            "prompt7_manual_score": (
                len(new_matched) / len(new_criteria) if new_criteria else None
            ),
        })

    def claim_text(agent: str, kind: str, fragment: str) -> str:
        for source in (prompt6_by_agent[agent], prompt7_by_agent[agent]):
            for claim in source.get("claims", []):
                if (
                    claim.get("kind") == kind
                    and fragment.lower() in claim.get("text", "").lower()
                ):
                    return claim["text"]
            analysis = source.get("analysis") or {}
            values = [analysis.get("summary", "")]
            values.extend(analysis.get("findings", []))
            values.extend(analysis.get("recommended_checks", []))
            for value in values:
                if isinstance(value, str) and fragment.lower() in value.lower():
                    return value
        return fragment

    findings = [
        {
            "run": "Prompt 6.0",
            "agent": "monitoring",
            "classification": "likely_validator_false_positive",
            "claim": claim_text("monitoring", "summary", "16.67 percent"),
            "evidence_paths": [
                "prometheus.metrics.http_error_rate.observations[0].latest_value",
                "prometheus.metrics.memory_usage.observations[0].latest_value",
            ],
            "assessment": (
                "The rounded 16.67% corresponds to 16.6667%, and 78,643,200 bytes "
                "is the exact supplied memory value; the validator split the "
                "thousands-separated number into separate tokens."
            ),
        },
        {
            "run": "Prompt 6.0",
            "agent": "cicd",
            "classification": "validator_flag_supported",
            "claim": claim_text("cicd", "findings", "Health check status is unavailable"),
            "evidence_paths": ["health.data.status", "health.data.http_status"],
            "assessment": (
                "Health was available and reported status ok / HTTP 200, so the "
                "model's unavailability assertion was contradicted by evidence."
            ),
        },
        {
            "run": "Prompt 6.0",
            "agent": "cicd",
            "classification": "validator_flag_supported",
            "claim": claim_text("cicd", "findings", "16.666.7%"),
            "evidence_paths": ["metrics.error_rate_percent"],
            "assessment": (
                "The response rendered the measured 16.6667% as malformed "
                "16.666.7%; this is not a valid representation of the value."
            ),
        },
        {
            "run": "Prompt 6.0",
            "agent": "infrastructure",
            "classification": "validator_false_negative",
            "claim": claim_text("infrastructure", "summary", "No health status"),
            "evidence_paths": [
                "docker.containers[0].health_status",
                "docker.containers[0].restart_count",
            ],
            "assessment": (
                "The response said health and restart evidence were unavailable, "
                "although the fixture supplied healthy status and restart_count 0."
            ),
        },
        {
            "run": "Prompt 6.0",
            "agent": "security",
            "classification": "validator_flag_supported",
            "claim": claim_text("security", "recommended_check", "brute force"),
            "evidence_paths": ["logs.events[*].msg"],
            "assessment": (
                "The logs establish an authentication-event sequence, not a "
                "brute-force classification or unauthorized intent."
            ),
        },
        {
            "run": "Prompt 7.1",
            "agent": "monitoring",
            "classification": "validator_false_negative_hallucination",
            "claim": claim_text("monitoring", "findings", "mycontainer"),
            "evidence_paths": [],
            "assessment": (
                "The final retry invented container name 'mycontainer' and "
                "recommended checking its logs. No container name or Docker "
                "telemetry exists in this scenario. The first attempt was "
                "on-topic and listed stale Prometheus observations, but it was "
                "truncated; the schema-valid retry was unrelated."
            ),
        },
        {
            "run": "Prompt 7.1",
            "agent": "incident",
            "classification": "overbroad_unverified_claim",
            "claim": claim_text("incident", "findings", "no errors"),
            "evidence_paths": [
                "metrics.requests.div.error",
                "logs.events[*].msg",
            ],
            "assessment": (
                "The deployment completed successfully, but the broader phrase "
                "'no errors' is not established by deployment status and the "
                "scenario includes increased application errors and timeout logs. "
                "Treat as scope-ambiguous, not a confirmed fabricated fact."
            ),
        },
        {
            "run": "Prompt 7.1",
            "agent": "code",
            "classification": "likely_validator_false_positive",
            "claim": claim_text("code", "findings", "No application logs provided"),
            "evidence_paths": ["deterministic_evidence.missing_evidence[application_log]"],
            "assessment": (
                "The role package explicitly marks application logs unavailable; "
                "the validator's claim that this absence cannot be confirmed is "
                "a source-availability false positive."
            ),
        },
        {
            "run": "Prompt 7.1",
            "agent": "infrastructure",
            "classification": "mixed_validator_false_positive_and_unverified_qualifier",
            "claim": claim_text("infrastructure", "findings", "734 MB"),
            "evidence_paths": [
                "docker.containers[0].memory_usage_bytes",
                "process.host_process_memory_mib",
            ],
            "assessment": (
                "734 MB is a valid decimal-unit rendering of 734003200 bytes "
                "(700 MiB), and 60 MiB exactly matches the process observation; "
                "the validator missed unit conversion. However, the qualitative "
                "word 'significant' has no supplied configured threshold, and the "
                "model's confidence 1.0 is overconfident for stale measurements."
            ),
        },
        {
            "run": "Prompt 7.1",
            "agent": "security",
            "classification": "likely_validator_false_positive",
            "claim": claim_text("security", "summary", "November 1, 2026"),
            "evidence_paths": [
                "logs.events[2].ts",
                "logs.events[3].ts",
            ],
            "assessment": (
                "The human-readable date/time corresponds to the supplied ISO "
                "timestamps; the validator treated date components 1 and 2026 "
                "as unsupported numbers. The response still omitted two earlier "
                "failed-event timestamps."
            ),
        },
    ]
    criteria_total = sum(
        len(item["prompt6_manual_matched"])
        + len(item["prompt6_manual_missed"])
        for item in reviews
    )
    prompt6_matched = sum(
        len(item["prompt6_manual_matched"]) for item in reviews
    )
    prompt7_matched = sum(
        len(item["prompt7_manual_matched"]) for item in reviews
    )
    return {
        "method": (
            "Independent review of captured Prompt 6.0 and Prompt 7.1 summaries, "
            "findings, recommendations, and source-linked evidence. Equivalent "
            "wording and unit conversions are accepted; stale facts count only "
            "when the final accepted response accurately identifies them as stale. "
            "Aggregate manual completeness is micro-averaged over the scenario "
            "criteria. These annotations do not modify the automated regex or "
            "validator scores."
        ),
        "agents": reviews,
        "summary": {
            "criteria_total": criteria_total,
            "prompt6_matched": prompt6_matched,
            "prompt7_matched": prompt7_matched,
            "prompt6_average_interpretation_completeness": (
                prompt6_matched / criteria_total if criteria_total else 0.0
            ),
            "prompt7_average_interpretation_completeness": (
                prompt7_matched / criteria_total if criteria_total else 0.0
            ),
            "prompt7_manual_missed_criteria": sum(
                len(item["prompt7_manual_missed"]) for item in reviews
            ),
            "prompt7_validator_reported_unsupported_claims": (
                report["summary"]["prompt7_unsupported_claims"]
            ),
            "prompt7_definite_unsupported_or_hallucinated_statements": 1,
            "prompt7_scope_ambiguous_or_unverified_overclaims": 2,
        },
        "findings": findings,
        "scoring_caveat": (
            "Manual review is qualitative and scenario-specific, not a blinded "
            "general benchmark. Raw automated scores are preserved separately."
        ),
    }


def _write_prompt71_reports(report: dict[str, Any]) -> None:
    PROMPT7_1_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT7_1_JSON_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    summary = report["summary"]
    lines = [
        "# Prompt 7.1 — Controlled Six-Agent Live Evaluation",
        "",
        f"- **Run (UTC):** {report['environment']['run_utc']}",
        f"- **Ollama:** `{report['environment']['ollama_url']}` "
        f"(version {report['environment']['ollama_version']})",
        f"- **Offline suite:** {report['offline_tests']['summary']}",
        f"- **Prompt 6.0 fixtures:** reused verbatim from `{report['comparison']['fixture_source']}`.",
        "- **Inference:** sequential; no deployment, rollback, or remediation executed.",
        "",
        "## Preflight and configuration",
        "",
        f"- Installed expected models: {len(report['environment']['installed_models'])}/6; missing: {report['environment']['missing_models'] or 'none'}.",
        f"- Models loaded before: {report['environment']['models_loaded_before']}; after: {report['environment']['models_loaded_after']}.",
        f"- Persistent `enabled`: `{report['safety']['persistent_enabled']}`; runtime override: temporary for this process only.",
        f"- `max_parallel_models`: `{report['environment']['runtime']['max_parallel_models']}`; runtime settings match Prompt 6.0: `{report['safety']['runtime_settings_match_prompt6']}`.",
        f"- Persistent config SHA-256 unchanged: `{report['safety']['config_unchanged']}`.",
        "",
        "## Per-agent results",
        "",
        "| Specialist | Model | Status | Extracted | Delivered | Usable fresh facts | Interpretation | Grounding score* | Unsupported claims | Ollama time (s) | Wall time (s) | Retries | Schema |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for entry in report["agents"]:
        matched, total, interpretation = _interpretation_score(entry)
        claim_count, unsupported_count = _claim_counts(entry)
        usable = sum(
            item.get("usable", False)
            for item in entry.get("required_fact_results", [])
        )
        lines.append(
            f"| {entry['agent']} | {entry['assigned_model']} | "
            f"{entry['overall_result']} | "
            f"{sum(x['extracted'] for x in entry['required_fact_results'])}/"
            f"{len(entry['required_fact_results'])} | "
            f"{sum(x['delivered'] for x in entry['required_fact_results'])}/"
            f"{len(entry['required_fact_results'])} | "
            f"{usable}/{len(entry['required_fact_results'])} | "
            f"{matched}/{total} ({interpretation:.1%}) | "
            f"{_grounding_score(entry):.1%} ({claim_count} claims) | "
            f"{unsupported_count} | {entry['ollama_inference_seconds']:.2f} | "
            f"{entry['latency_seconds']:.2f} | {entry['retry_count']} | "
            f"{entry['json_schema_valid']} |"
        )
    lines.extend([
        "",
        "*Grounding score is a validator-based ratio: 1 − materially unsupported response strings / assessed response strings. It is not a semantic truth guarantee.",
        "",
        "## Prompt 6.0 versus Prompt 7.1",
        "",
        "The interpretation rubric uses the same scenario criteria and `_grade_agent` checks as Prompt 6.0. Prompt 6.0 did not measure extraction or delivery, so those comparisons are explicitly unavailable. Grounding scores use the same material-unsupported validator data and response-string denominator, with the limitations above.",
        "",
        "| Specialist | P6 extraction | P7.1 extraction | P6 delivery | P7.1 delivery | P6 interpretation | P7.1 interpretation | Change | P6 grounding | P7.1 grounding | P6 unsupported | P7.1 unsupported |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|",
    ])
    for item in report["comparison"]["agents"]:
        lines.append(
            f"| {item['agent']} | not measured | "
            f"{item['prompt7_extraction_completeness']:.1%} | "
            f"not measured | {item['prompt7_delivery_completeness']:.1%} | "
            f"{item['prompt6_interpretation']} | {item['prompt7_interpretation']} | "
            f"{item['interpretation_change']} | {item['prompt6_grounding']} | "
            f"{item['prompt7_grounding']} | {item['prompt6_unsupported_claims']} | "
            f"{item['prompt7_unsupported_claims']} |"
        )
    lines.extend([
        "",
        "## Aggregate comparison",
        "",
        f"- Average interpretation completeness: Prompt 6.0 {summary['prompt6_average_interpretation_completeness']:.1%}; Prompt 7.1 {summary['prompt7_average_interpretation_completeness']:.1%}.",
        f"- Average validator-based grounding score: Prompt 6.0 {summary['prompt6_average_grounding_score']:.1%}; Prompt 7.1 {summary['prompt7_average_grounding_score']:.1%}.",
        f"- Unsupported claims: Prompt 6.0 {summary['prompt6_unsupported_claims']}; Prompt 7.1 {summary['prompt7_unsupported_claims']}.",
        f"- Missed required criteria: Prompt 6.0 {summary['prompt6_missed_criteria']}; Prompt 7.1 {summary['prompt7_missed_criteria']}.",
        f"- Schema-valid responses: Prompt 6.0 {summary['prompt6_schema_valid']}/6; Prompt 7.1 {summary['prompt7_schema_valid']}/6.",
        f"- Total Ollama inference time: Prompt 6.0 {summary['prompt6_inference_seconds']:.2f}s; Prompt 7.1 {summary['prompt7_inference_seconds']:.2f}s.",
        f"- Prompt 7.1 total wall time: {summary['prompt7_total_wall_seconds']:.2f}s.",
        f"- Prompt 7.1 total evaluation duration (including preflight and offline tests): {summary['prompt7_total_evaluation_seconds']:.2f}s.",
        "",
        "## Failure analysis",
        "",
    ])
    failures = [
        (entry, next(
            item for item in report["comparison"]["prompt6_agents"]
            if item["agent"] == entry["agent"]
        ))
        for entry in report["agents"]
        if entry["overall_result"] in {"PARTIAL", "FAIL"}
    ]
    if not failures:
        lines.append("No agent was graded PARTIAL or FAIL under the configured criteria.")
    for entry, baseline_entry in failures:
        lines.append(f"### {entry['agent']} — {entry['overall_result']}")
        if entry.get("failure_analysis"):
            for failure in entry["failure_analysis"]:
                lines.append(f"- {json.dumps(failure, ensure_ascii=False)}")
        else:
            lines.append("- No criterion-level miss; see unsupported claim and grader fields in JSON.")
    manual = report.get("manual_review")
    if isinstance(manual, dict):
        manual_summary = manual["summary"]
        lines.extend([
            "",
            "## Manual semantic review",
            "",
            manual["method"],
            "",
            "| Specialist | Prompt 6.0 manual interpretation | Prompt 7.1 manual interpretation |",
            "|---|---:|---:|",
        ])
        for item in manual["agents"]:
            old_count = len(item["prompt6_manual_matched"])
            old_total = old_count + len(item["prompt6_manual_missed"])
            new_count = len(item["prompt7_manual_matched"])
            new_total = new_count + len(item["prompt7_manual_missed"])
            lines.append(
                f"| {item['agent']} | {old_count}/{old_total} "
                f"({item['prompt6_manual_score']:.1%}) | {new_count}/{new_total} "
                f"({item['prompt7_manual_score']:.1%}) |"
            )
        lines.extend([
            "",
            f"- Manual average interpretation completeness: Prompt 6.0 {manual_summary['prompt6_average_interpretation_completeness']:.1%}; Prompt 7.1 {manual_summary['prompt7_average_interpretation_completeness']:.1%}.",
            f"- Prompt 7.1 manual missed criteria: {manual_summary['prompt7_manual_missed_criteria']}.",
            f"- Prompt 7.1 validator-reported unsupported claim strings: {manual_summary['prompt7_validator_reported_unsupported_claims']}; definite hallucinated/unsupported statements found by manual review: {manual_summary['prompt7_definite_unsupported_or_hallucinated_statements']}; scope-ambiguous or unverified overclaims: {manual_summary['prompt7_scope_ambiguous_or_unverified_overclaims']}.",
            "",
            "### Validator and model claim review",
            "",
        ])
        for finding in manual["findings"]:
            lines.append(
                f"- **{finding['run']} / {finding['agent']} — "
                f"{finding['classification']}:** {finding['assessment']} "
                f"Evidence paths: `{', '.join(finding['evidence_paths']) or 'none'}`."
            )
        lines.extend(["", manual["scoring_caveat"], ""])
    lines.extend([
        "",
        "## Output separation and safety",
        "",
        "- Deterministic verified observations are sourced only from the extractor; model statements remain interpretations, hypotheses, recommendations, or unverified claims.",
        "- Hypotheses are never promoted to verified observations. Recommendations are recorded as advisory and not executed.",
        f"- Sequential overlap detected: `{report['sequential_overlap_detected']}`.",
        f"- No remediation/deployment/rollback executed: `{report['safety']['operational_actions_not_executed']}`.",
        "",
        "## Limitations and next steps",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
        "The JSON companion contains all per-agent raw redacted responses, prompts, extracted and delivered evidence IDs, source paths, claim validations, retries, timings, and exact comparison inputs.",
        "",
    ])
    PROMPT7_1_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_prompt7_1_live_evaluation() -> dict[str, Any]:
    """Run the exact Prompt 6.0 fixtures sequentially without overwriting them."""
    started_at = time.perf_counter()
    model_config_path = ROOT / "config" / "models.json"
    config_bytes_before = model_config_path.read_bytes()
    config_hash_before = hashlib.sha256(config_bytes_before).hexdigest()
    persistent_config = json.loads(config_bytes_before)
    effective_config_path = Path(os.getenv(
        "DEVOPS_MODEL_CONFIG", str(llm_runtime.DEFAULT_CONFIG)
    )).resolve()
    if effective_config_path != model_config_path.resolve():
        raise RuntimeError(
            "Preflight failed: DEVOPS_MODEL_CONFIG overrides the required persistent config."
        )
    prompt6_report = json.loads(JSON_REPORT_PATH.read_text(encoding="utf-8"))
    prompt6_grounding = _prompt6_grounding_results()
    scenarios = _prompt6_scenarios_from_report()
    if (
        prompt6_report.get("environment", {}).get("run_utc")
        != prompt6_grounding.get("environment", {}).get("run_utc")
    ):
        raise ValueError(
            "Prompt 6.0 live and grounding reports are from different evaluation runs."
        )
    grounding_agents = {
        item["agent"]: item for item in prompt6_grounding["agents"]
    }
    for name, scenario in scenarios.items():
        baseline_entry = grounding_agents[name]
        if (
            baseline_entry.get("original_synthetic_evidence")
            != scenario["evidence"]
            or baseline_entry.get("scenario_summary") != scenario["task"]
            or baseline_entry.get("expected_criteria")
            != scenario["expected_criteria"]
        ):
            raise ValueError(
                f"Prompt 6.0 live and grounding inputs disagree for {name}; "
                "cannot make a controlled comparison."
            )
    cfg = llm_runtime.load_config()
    runtime = cfg.get("runtime", {})
    prompt6_runtime = prompt6_report.get("environment", {}).get("runtime", {})
    runtime_keys = (
        "max_parallel_models", "keep_alive", "context_length",
        "max_output_tokens", "request_timeout_seconds", "temperature",
    )
    runtime_matches = all(
        runtime.get(key) == prompt6_runtime.get(key) for key in runtime_keys
    )
    mappings = {
        name: llm_runtime.model_for(name, cfg) for name in AGENT_ORDER
    }
    if persistent_config.get("enabled") is not False:
        raise RuntimeError("Preflight failed: persistent models.json enabled is not false.")
    if mappings != EXPECTED_MODELS:
        raise RuntimeError(f"Preflight failed: model mapping mismatch: {mappings!r}")
    if runtime.get("max_parallel_models") != 1:
        raise RuntimeError("Preflight failed: max_parallel_models must be 1.")
    if not runtime_matches:
        raise RuntimeError(
            "Preflight failed: runtime timeout/token settings differ from Prompt 6.0."
        )

    installed, missing, base_url = _expected_installed_tags()
    cfg["_installed_models"] = installed
    try:
        version_response = requests.get(base_url + "/api/version", timeout=5)
        version_response.raise_for_status()
        ollama_version = version_response.json().get("version")
        before_processes = _ollama_processes(base_url)
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise RuntimeError(f"Preflight failed: Ollama unavailable: {exc}") from exc
    loaded_before = (
        before_processes.get("models")
        if isinstance(before_processes, dict)
        else None
    )
    if missing:
        raise RuntimeError(
            "Preflight failed: required local models are missing: "
            + ", ".join(missing)
        )
    if loaded_before != [] or before_processes.get("error"):
        raise RuntimeError(
            "Preflight failed: Ollama must report no loaded models; "
            f"observed {before_processes!r}"
        )

    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    test_output = test_result.stdout + test_result.stderr
    if test_result.returncode:
        raise RuntimeError(
            "Offline pytest suite failed; live inference was not started.\n"
            + test_output[-4000:]
        )
    test_counts = _parse_pytest_summary(test_output)
    offline_tests = {
        "command": "python -m pytest -q",
        "return_code": test_result.returncode,
        "counts": test_counts,
        "summary": (
            f"{test_counts['passed']} passed, {test_counts['failed']} failed, "
            f"{test_counts['skipped']} skipped"
        ),
    }
    # Tests are offline; repeat the unloaded-model preflight immediately before inference.
    before_processes = _ollama_processes(base_url)
    if not isinstance(before_processes, dict) or before_processes.get("models") != []:
        raise RuntimeError(
            "Preflight failed after offline tests: Ollama reports loaded models."
        )

    environment = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "ollama_url": _safe_url(base_url),
        "ollama_version": ollama_version,
        "python": platform.python_version(),
        "gpu": _gpu_info(),
        "installed_models": installed,
        "missing_models": missing,
        "model_mappings": mappings,
        "runtime": {key: runtime.get(key) for key in runtime_keys},
        "runtime_settings_match_prompt6": runtime_matches,
        "models_loaded_before": len(before_processes.get("models", [])),
        "models_loaded_before_details": before_processes.get("models", []),
    }
    previous_override = os.environ.get("DEVOPS_LLM_ENABLED")
    entries = []
    previous_end = None
    overlap_detected = False
    inference_started = time.perf_counter()
    try:
        os.environ["DEVOPS_LLM_ENABLED"] = "true"
        for name in AGENT_ORDER:
            entry, previous_end = _evaluate_one(
                name,
                scenarios[name],
                cfg,
                base_url,
                previous_end,
                include_prompt7_evidence=True,
            )
            entry["scenario_summary"] = scenarios[name]["task"]
            overlap_detected = overlap_detected or not entry["no_overlap_with_previous"]
            entries.append(entry)
    finally:
        if previous_override is None:
            os.environ.pop("DEVOPS_LLM_ENABLED", None)
        else:
            os.environ["DEVOPS_LLM_ENABLED"] = previous_override
    inference_wall_seconds = time.perf_counter() - inference_started

    after_processes = _ollama_processes(base_url)
    deadline = time.monotonic() + 15
    while (
        isinstance(after_processes, dict)
        and after_processes.get("models")
        and time.monotonic() < deadline
    ):
        time.sleep(0.5)
        after_processes = _ollama_processes(base_url)
    config_hash_after = hashlib.sha256(model_config_path.read_bytes()).hexdigest()
    environment["models_loaded_after"] = (
        len(after_processes.get("models", []))
        if isinstance(after_processes, dict)
        and isinstance(after_processes.get("models"), list)
        else None
    )
    environment["models_loaded_after_details"] = (
        after_processes.get("models")
        if isinstance(after_processes, dict) else None
    )
    environment["run_wall_seconds"] = time.perf_counter() - started_at
    environment["inference_loop_wall_seconds"] = inference_wall_seconds

    baseline_agents = {
        item["agent"]: item
        for item in prompt6_grounding.get("agents", [])
    }
    comparison_agents = []
    for entry in entries:
        baseline = baseline_agents[entry["agent"]]
        old_matched, old_total, old_interpretation = _interpretation_score(baseline)
        new_matched, new_total, new_interpretation = _interpretation_score(entry)
        if old_total != new_total:
            raise ValueError(
                f"Prompt 6.0 and 7.1 criterion counts differ for {entry['agent']}: "
                f"{old_total} versus {new_total}"
            )
        old_grounding = _grounding_score(baseline)
        new_grounding = _grounding_score(entry)
        old_claim_count, old_unsupported = _claim_counts(baseline)
        new_claim_count, new_unsupported = _claim_counts(entry)
        comparison_agents.append({
            "agent": entry["agent"],
            "prompt6_extraction_completeness": None,
            "prompt7_extraction_completeness": entry["extraction_completeness"],
            "prompt6_delivery_completeness": None,
            "prompt7_delivery_completeness": entry["delivery_completeness"],
            "prompt6_interpretation": (
                f"{old_matched}/{old_total} ({old_interpretation:.1%})"
                if old_interpretation is not None else "not measured"
            ),
            "prompt7_interpretation": (
                f"{new_matched}/{new_total} ({new_interpretation:.1%})"
                if new_interpretation is not None else "not measured"
            ),
            "interpretation_change": (
                f"{new_interpretation - old_interpretation:+.1%}"
                if old_interpretation is not None
                and new_interpretation is not None else "not comparable"
            ),
            "prompt6_grounding": (
                f"{old_grounding:.1%}" if old_grounding is not None else "not measured"
            ),
            "prompt7_grounding": (
                f"{new_grounding:.1%}" if new_grounding is not None else "not measured"
            ),
            "prompt6_unsupported_claims": old_unsupported,
            "prompt7_unsupported_claims": new_unsupported,
            "prompt6_claim_strings": old_claim_count,
            "prompt7_claim_strings": new_claim_count,
            "prompt6_result": baseline.get("overall_result"),
            "prompt7_result": entry.get("overall_result"),
        })
        entry["failure_analysis"] = _prompt71_failure_analysis(entry, baseline)
        categories = entry["response_categories"]
        categories["verified_observations"] = entry["evidence_delivery"]["observations"]

    prompt6_interpretation_scores = [
        _interpretation_score(item)[2]
        for item in prompt6_grounding["agents"]
        if _interpretation_score(item)[2] is not None
    ]
    prompt7_interpretation_scores = [
        _interpretation_score(item)[2]
        for item in entries
        if _interpretation_score(item)[2] is not None
    ]
    prompt6_grounding_scores = [
        _grounding_score(item) for item in prompt6_grounding["agents"]
        if _grounding_score(item) is not None
    ]
    prompt7_grounding_scores = [
        _grounding_score(item) for item in entries
        if _grounding_score(item) is not None
    ]
    summary = {
        "agents_total": len(entries),
        "pass": sum(item["overall_result"] == "PASS" for item in entries),
        "partial": sum(item["overall_result"] == "PARTIAL" for item in entries),
        "failed": sum(item["overall_result"] == "FAIL" for item in entries),
        "skipped": sum(item["overall_result"] == "SKIPPED" for item in entries),
        "inference_ok": sum(item["inference_status"] == "ok" for item in entries),
        "prompt7_schema_valid": sum(item["json_schema_valid"] is True for item in entries),
        "prompt6_schema_valid": prompt6_grounding["summary"].get("schema_valid"),
        "prompt6_average_interpretation_completeness": sum(
            prompt6_interpretation_scores
        ) / len(prompt6_interpretation_scores) if prompt6_interpretation_scores else 0,
        "prompt7_average_interpretation_completeness": sum(
            prompt7_interpretation_scores
        ) / len(prompt7_interpretation_scores) if prompt7_interpretation_scores else 0,
        "prompt6_average_grounding_score": sum(
            prompt6_grounding_scores
        ) / len(prompt6_grounding_scores) if prompt6_grounding_scores else 0,
        "prompt7_average_grounding_score": sum(
            prompt7_grounding_scores
        ) / len(prompt7_grounding_scores) if prompt7_grounding_scores else 0,
        "prompt6_unsupported_claims": sum(
            _claim_counts(item)[1] for item in prompt6_grounding["agents"]
        ),
        "prompt7_unsupported_claims": sum(_claim_counts(item)[1] for item in entries),
        "prompt6_missed_criteria": sum(
            len(item.get("missing_observations", []))
            for item in prompt6_grounding["agents"]
        ),
        "prompt7_missed_criteria": sum(
            len(item.get("missing_observations", [])) for item in entries
        ),
        "prompt6_inference_seconds": prompt6_grounding["summary"].get(
            "total_inference_seconds", 0
        ),
        "prompt7_inference_seconds": sum(
            item["ollama_inference_seconds"] for item in entries
        ),
        "prompt6_total_wall_seconds": prompt6_grounding["summary"].get(
            "total_wall_seconds", 0
        ),
        "prompt7_total_wall_seconds": sum(
            item["latency_seconds"] for item in entries
        ),
        "prompt7_total_evaluation_seconds": environment["run_wall_seconds"],
        "prompt7_evidence_facts_total": sum(
            len(item["required_fact_results"]) for item in entries
        ),
        "prompt7_evidence_facts_extracted": sum(
            item["extracted"]
            for entry in entries
            for item in entry["required_fact_results"]
        ),
        "prompt7_evidence_facts_delivered": sum(
            item["delivered"]
            for entry in entries
            for item in entry["required_fact_results"]
        ),
        "prompt7_evidence_facts_usable": sum(
            item["usable"]
            for entry in entries
            for item in entry["required_fact_results"]
        ),
    }
    report = {
        "report_version": 1,
        "environment": environment,
        "offline_tests": offline_tests,
        "comparison": {
            "prompt6_live_report": str(JSON_REPORT_PATH.relative_to(ROOT)),
            "prompt6_grounding_report": str(GROUNDING_JSON_PATH.relative_to(ROOT)),
            "fixture_source": str(JSON_REPORT_PATH.relative_to(ROOT)),
            "query_source": (
                "Prompt 6.0 report did not persist graph query strings; the unchanged "
                "scenario query string is reused from the current evaluation harness."
            ),
            "comparison_input_source": (
                "Prompt 6.0 report did not persist pre-graph comparison inputs; "
                "the existing scenario comparison fixture is reused from the current harness."
            ),
            "prompt6_run_utc": prompt6_report.get("environment", {}).get("run_utc"),
            "prompt6_scoring_run_utc": prompt6_grounding.get(
                "environment", {}
            ).get("run_utc"),
            "scoring": {
                "interpretation": (
                    "Same _grade_agent required-observation regex criteria and "
                    "scenario fixture criteria in Prompt 6.0 and Prompt 7.1."
                ),
                "grounding": (
                    "Same material_unsupported_claims validator output divided by "
                    "all response strings in claims; heuristic, not semantic proof."
                ),
                "extraction_delivery": (
                    "Not measured in Prompt 6.0; Prompt 7.1 uses deterministic "
                    "evidence IDs and the configured role category filters."
                ),
            },
            "agents": comparison_agents,
            "prompt6_agents": prompt6_grounding["agents"],
        },
        "scenarios": {
            name: {
                "task": scenario["task"],
                "query": scenario["query"],
                "comparison": scenario["comparison"],
                "expected_criteria": scenario["expected_criteria"],
                "original_synthetic_evidence": _safe_report_value(
                    scenario["evidence"]
                ),
            }
            for name, scenario in scenarios.items()
        },
        "agents": entries,
        "summary": summary,
        "safety": {
            "persistent_enabled": persistent_config.get("enabled"),
            "config_sha256_before": config_hash_before,
            "config_sha256_after": config_hash_after,
            "config_unchanged": config_hash_before == config_hash_after,
            "runtime_settings_match_prompt6": runtime_matches,
            "live_inference_enabled_only_by_temporary_process_override": True,
            "operational_actions_not_executed": True,
            "models_unloaded_after_evaluation": environment["models_loaded_after"] == 0,
        },
        "sequential_overlap_detected": overlap_detected,
        "limitations": [
            "Prompt 6.0 did not score deterministic extraction or role delivery, so no historical comparison is possible for those categories.",
            "The interpretation grader uses the same explicit regex acceptance criteria as Prompt 6.0; it is not a general semantic benchmark.",
            "Grounding score is based on the existing validator and response-string counts; it can contain false positives/negatives and is not an independent truth assessment.",
            "Prompt 6.0 fixtures are reused verbatim, so their telemetry timestamps may be stale at Prompt 7.1 evaluation time; freshness status is reported separately from extraction/delivery.",
            "The Prompt 6.0 report did not persist per-scenario graph query strings. Prompt 7.1 reuses the query field from the existing evaluation harness and records this limitation.",
            "The Prompt 6.0 report did not persist pre-graph comparison fixture inputs; Prompt 7.1 reuses the existing scenario comparison values from the harness.",
        ],
    }
    report["manual_review"] = _prompt71_manual_review(report)
    _write_prompt71_reports(report)
    return report


def run_prompt7_offline_evaluation() -> dict[str, Any]:
    """Run offline tests, then write both Prompt 7 reports from one data object."""
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    test_output = test_result.stdout + test_result.stderr
    if test_result.returncode:
        raise RuntimeError(
            "Offline pytest suite failed; reports were not generated.\n"
            + test_output[-4000:]
        )
    counts = _parse_pytest_summary(test_output)
    offline_tests = {
        "command": "python -m pytest -q",
        "return_code": test_result.returncode,
        "counts": counts,
        "summary": (
            f"{counts['passed']} passed, {counts['failed']} failed, "
            f"{counts['skipped']} skipped"
        ),
    }
    report = _build_prompt7_offline_report(offline_tests)
    _write_prompt7_reports(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt7-offline",
        action="store_true",
        help="Run offline evidence-extraction evaluation and write Prompt 7 reports; does not invoke Ollama.",
    )
    parser.add_argument(
        "--prompt7-1-live",
        action="store_true",
        help="Run controlled Prompt 7.1 inference on exact Prompt 6.0 fixtures and write isolated reports.",
    )
    parser.add_argument(
        "--prompt7-1-audit",
        action="store_true",
        help="Add manual semantic-review annotations to captured Prompt 7.1 results without Ollama calls.",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Acknowledge this will make sequential requests to the configured local Ollama server.",
    )
    args = parser.parse_args()
    if args.prompt7_offline:
        report = run_prompt7_offline_evaluation()
        print(json.dumps({
            "report": str(PROMPT7_REPORT_PATH),
            "json_results": str(PROMPT7_JSON_PATH),
            "summary": report["summary"],
            "offline_tests": report["offline_tests"]["summary"],
            "live_inference": "not_run",
        }, indent=2))
        return 0
    if args.prompt7_1_live:
        report = run_prompt7_1_live_evaluation()
        print(json.dumps({
            "report": str(PROMPT7_1_REPORT_PATH),
            "json_results": str(PROMPT7_1_JSON_PATH),
            "summary": report["summary"],
            "offline_tests": report["offline_tests"]["summary"],
            "overlap_detected": report["sequential_overlap_detected"],
            "results": [
                {
                    "agent": item["agent"],
                    "model": item["assigned_model"],
                    "status": item["inference_status"],
                    "schema_valid": item.get("json_schema_valid"),
                    "extraction_completeness": item.get("extraction_completeness"),
                    "delivery_completeness": item.get("delivery_completeness"),
                    "interpretation_result": item.get("overall_result"),
                    "inference_seconds": item.get("ollama_inference_seconds"),
                    "retry_count": item.get("retry_count"),
                }
                for item in report["agents"]
            ],
            "models_loaded_after": report["environment"]["models_loaded_after"],
            "persistent_config_unchanged": report["safety"]["config_unchanged"],
        }, indent=2))
        return 0 if report["safety"]["config_unchanged"] else 1
    if args.prompt7_1_audit:
        report = json.loads(PROMPT7_1_JSON_PATH.read_text(encoding="utf-8"))
        report["manual_review"] = _prompt71_manual_review(report)
        _write_prompt71_reports(report)
        print(json.dumps({
            "report": str(PROMPT7_1_REPORT_PATH),
            "json_results": str(PROMPT7_1_JSON_PATH),
            "manual_summary": report["manual_review"]["summary"],
            "live_inference": "not_run",
        }, indent=2))
        return 0
    if not args.confirm_live:
        parser.error("Pass --confirm-live to run actual local Ollama inference.")
    if os.getenv("DEVOPS_LLM_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        parser.error(
            "Set DEVOPS_LLM_ENABLED=true for this process only; config/models.json remains unchanged."
        )
    report = run_evaluation()
    print(json.dumps({
        "report": str(REPORT_PATH),
        "json_results": str(JSON_REPORT_PATH),
        "grounding_report": str(GROUNDING_REPORT_PATH),
        "grounding_json": str(GROUNDING_JSON_PATH),
        "summary": report["summary"],
        "overlap_detected": report["sequential_overlap_detected"],
        "results": [
            {
                "agent": item["agent"],
                "model": item["assigned_model"],
                "status": item["inference_status"],
                "schema_valid": item.get("json_schema_valid"),
                "latency_seconds": item.get("latency_seconds"),
                "retry_count": item.get("retry_count"),
                "overall_result": item.get("overall_result"),
            }
            for item in report["agents"]
        ],
    }, indent=2))
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
