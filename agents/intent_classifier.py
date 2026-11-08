"""Natural-language incident intent classifier and specialist agent router.

Classifies operator queries into the five synthetic incident scenarios:
1. DEPLOYMENT_REGRESSION
2. PERFORMANCE_DRIFT
3. INFRASTRUCTURE_FAILURE
4. SECURITY_AUDIT
5. GENERAL_INCIDENT

Supports multi-category detection, synonyms, conversational queries,
and deterministic fallback routing.
"""
from __future__ import annotations

import re
from typing import Any

from agents.scenarios import (
    SCENARIO_DEPLOYMENT_REGRESSION,
    SCENARIO_PERFORMANCE_DRIFT,
    SCENARIO_INFRASTRUCTURE_FAILURE,
    SCENARIO_SECURITY_AUDIT,
    SCENARIO_GENERAL_INCIDENT,
    SCENARIO_DEFINITIONS,
)

# Regex pattern dictionaries for deterministic classification
PATTERNS = {
    SCENARIO_DEPLOYMENT_REGRESSION: [
        r"\b(?:deploy(?:ed|ment)?|release|v1\.1|version\s*1\.1|rollback)\b",
        r"\b(?:division|div(?:ide)?|handler|crash(?:ed|es|ing)?|zero\s*division)\b",
        r"\b(?:500|5xx|http\s*500|internal\s*server\s*error)\b",
        r"\b(?:regression|faulty\s*(?:release|build|commit))\b",
    ],
    SCENARIO_PERFORMANCE_DRIFT: [
        r"\b(?:request\s*rate|traffic|throughput|rps)\b",
        r"\b(?:latenc(?:y|ies)|response\s*time|p95|slow(?:down)?|delay|lag)\b",
        r"\b(?:spike|drift|bottleneck|saturation|high\s*load)\b",
        r"\b(?:error\s*distribution|anomalous\s*(?:http|error|metric))\b",
    ],
    SCENARIO_INFRASTRUCTURE_FAILURE: [
        r"\b(?:docker|container|compose|daemon|engine)\b",
        r"\b(?:host\s*memory|host\s*cpu|cpu\s*pressure|memory\s*pressure|ram|ooms?)\b",
        r"\b(?:scrape|target|prometheus\s*scrape|readiness|unhealthy|restart)\b",
        r"\b(?:service\s*down|connection\s*refused|infrastructure)\b",
    ],
    SCENARIO_SECURITY_AUDIT: [
        r"\b(?:secur(?:ity|e)|cve|vulnerabilit(?:y|ies)|exploit)\b",
        r"\b(?:secret|token|leak(?:ed|s)?|credential|trufflehog|gitleaks)\b",
        r"\b(?:trivy|semgrep|sast|static\s*analysis|audit|cve-\d+)\b",
        r"\b(?:build\s*artifacts|package\s*vulnerabilit|dependency\s*check)\b",
    ],
    SCENARIO_GENERAL_INCIDENT: [
        r"\b(?:calculator\s+is\s+throwing\s+errors|what\s+is\s+wrong|how\s+do\s+we\s+fix\s+it)\b",
        r"\b(?:full\s*investigation|complete\s*investigation|all\s*(?:specialists|agents|systems))\b",
        r"\b(?:troubleshoot\s*everything|end-to-end\s*diagnosis|general\s*incident)\b",
    ],
}

AGENT_ROUTING = {
    SCENARIO_DEPLOYMENT_REGRESSION: ["monitoring", "incident", "code", "cicd", "infrastructure"],
    SCENARIO_PERFORMANCE_DRIFT: ["monitoring", "incident", "infrastructure", "code"],
    SCENARIO_INFRASTRUCTURE_FAILURE: ["infrastructure", "monitoring", "incident"],
    SCENARIO_SECURITY_AUDIT: ["security", "cicd", "code"],
    SCENARIO_GENERAL_INCIDENT: [
        "monitoring",
        "incident",
        "code",
        "cicd",
        "infrastructure",
        "security",
    ],
}


def classify_incident_intent(
    query: str,
    evidence: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the operator's natural language query into incident scenarios."""
    cleaned = (query or "").strip().lower()
    if not cleaned:
        return {
            "primary_scenario": SCENARIO_GENERAL_INCIDENT,
            "detected_scenarios": [SCENARIO_GENERAL_INCIDENT],
            "scenarios_detected": [SCENARIO_GENERAL_INCIDENT],
            "confidence": 0.5,
            "classification_method": "deterministic_fallback",
            "rationale": "Empty query defaulted to general full investigation.",
            "recommended_agents": list(AGENT_ROUTING[SCENARIO_GENERAL_INCIDENT]),
            "requires_all_agents": True,
        }

    # Score each scenario based on keyword/regex match counts
    scores: dict[str, int] = {sid: 0 for sid in PATTERNS}

    for sid, pattern_list in PATTERNS.items():
        for pat in pattern_list:
            if re.search(pat, cleaned, re.IGNORECASE):
                scores[sid] += 1

    # Check for explicit General / Complete indicators
    is_explicit_general = bool(
        scores[SCENARIO_GENERAL_INCIDENT] > 0
        or any(
            phrase in cleaned
            for phrase in (
                "what is wrong",
                "how do we fix",
                "throwing errors",
                "full investigation",
                "complete investigation",
                "all agents",
                "all specialists",
            )
        )
    )

    detected: list[str] = [sid for sid, score in scores.items() if score > 0]

    # If general was explicitly asked, or multiple non-overlapping categories are matched
    if is_explicit_general or len(detected) >= 3:
        primary = SCENARIO_GENERAL_INCIDENT
        if SCENARIO_GENERAL_INCIDENT not in detected:
            detected.append(SCENARIO_GENERAL_INCIDENT)
        recommended = list(AGENT_ROUTING[SCENARIO_GENERAL_INCIDENT])
        requires_all = True
    elif detected:
        # Pick the scenario with highest match score
        primary = max(scores.keys(), key=lambda k: scores[k])
        recommended_set = set(AGENT_ROUTING[primary])
        for d in detected:
            if d != SCENARIO_GENERAL_INCIDENT:
                recommended_set.update(AGENT_ROUTING.get(d, []))
        canonical_order = (
            "monitoring",
            "incident",
            "code",
            "cicd",
            "infrastructure",
            "security",
        )
        recommended = [a for a in canonical_order if a in recommended_set]
        requires_all = len(recommended) == 6
    else:
        # Unclassified generic query; fallback without overriding evidence-based routing
        primary = SCENARIO_GENERAL_INCIDENT
        recommended = []
        requires_all = False

    # Check evidence signals if available to refine confidence
    confidence = 0.85 if scores[primary] >= 2 else 0.70
    if comparison:
        if comparison.get("deployment_changed") and primary == SCENARIO_DEPLOYMENT_REGRESSION:
            confidence = min(1.0, confidence + 0.1)
        if comparison.get("regression_signal") and primary in (
            SCENARIO_DEPLOYMENT_REGRESSION,
            SCENARIO_PERFORMANCE_DRIFT,
        ):
            confidence = min(1.0, confidence + 0.05)

    rationale = (
        f"Matched {scores[primary]} pattern(s) for {primary}."
        if primary in scores and scores[primary] > 0
        else f"Selected {primary} based on broad cross-domain query semantics."
    )

    return {
        "primary_scenario": primary,
        "detected_scenarios": detected or [primary],
        "scenarios_detected": detected or [primary],
        "confidence": round(confidence, 2),
        "classification_method": "deterministic_rule",
        "rationale": rationale,
        "recommended_agents": recommended,
        "requires_all_agents": requires_all,
        "definition": SCENARIO_DEFINITIONS.get(primary),
    }


def get_specialist_routing_for_query(query: str) -> dict[str, Any]:
    """Return the selected specialist agents and intent classification for a query."""
    classification = classify_incident_intent(query)
    return {
        "primary_scenario": classification["primary_scenario"],
        "selected_specialists": classification["recommended_agents"],
        "requires_all_agents": classification["requires_all_agents"],
        "detected_scenarios": classification["detected_scenarios"],
    }
