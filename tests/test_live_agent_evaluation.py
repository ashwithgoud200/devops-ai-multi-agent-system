import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("live_agent_evaluation.py")
SPEC = importlib.util.spec_from_file_location("live_agent_evaluation", MODULE_PATH)
live_evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_evaluation)


def test_synthetic_scenarios_route_through_production_evidence_shaping():
    scenarios = live_evaluation._scenario_data()

    for agent in live_evaluation.AGENT_ORDER:
        state = live_evaluation._routing_state(agent, scenarios[agent])
        assert agent in live_evaluation.graph._select_specialists(state)
        shaped = live_evaluation.graph._specialist_evidence(agent, state)
        assert shaped

    security = live_evaluation._routing_state(
        "security", scenarios["security"]
    )
    security_payload = live_evaluation.graph._specialist_evidence(
        "security", security
    )
    assert len(security_payload["security_events"]["events"]) == 4
    assert security_payload["security_events"]["events"][-1]["ts"] > (
        security_payload["security_events"]["events"][0]["ts"]
    )
    assert "docker" not in security_payload
    assert "prometheus" not in security_payload


def test_monitoring_fixture_keeps_prometheus_rates_out_of_counter_fields():
    scenario = live_evaluation._scenario_data()["monitoring"]
    state = live_evaluation._routing_state("monitoring", scenario)
    shaped = live_evaluation.graph._specialist_evidence("monitoring", state)
    facts = shaped["verified_observations"]

    assert shaped["metrics"]["status"] == "unavailable"
    assert not any("Cumulative" in fact["statement"] for fact in facts)
    assert any(
        fact["source"].startswith("prometheus.metrics.http_error_rate")
        for fact in facts
    )
    assert any(
        fact["source"].startswith("prometheus.metrics.memory_usage")
        and "78643200" in fact["statement"]
        for fact in facts
    )


def test_live_result_requires_evidence_criteria_not_only_valid_schema():
    scenario = live_evaluation._scenario_data()["monitoring"]
    sufficient = {
        "summary": (
            "Observed request rate 12/s, successful 10/s, errors 2/s, "
            "error rate 16.6667%, p95 latency 0.85 seconds, process CPU 88%, "
            "and process memory 75 MiB."
        ),
        "findings": [],
        "confidence": 0.8,
        "recommended_checks": [],
    }
    complete = live_evaluation._grade_agent(
        "monitoring", scenario, sufficient, [], "ok", True, True, True
    )
    incomplete = live_evaluation._grade_agent(
        "monitoring",
        scenario,
        {"summary": "Insufficient evidence.", "findings": [], "recommended_checks": []},
        [],
        "ok",
        True,
        True,
        True,
    )

    assert complete["overall_result"] == "PASS"
    assert incomplete["overall_result"] == "PARTIAL"
    assert incomplete["missing_observations"]


def test_report_sanitizer_redacts_credentials_from_prompt_material():
    sanitized = live_evaluation._safe_report_value({
        "prompt": 'password: "synthetic-secret" and api_key=synthetic-key'
    })

    assert "synthetic-secret" not in sanitized["prompt"]
    assert "synthetic-key" not in sanitized["prompt"]


def test_pytest_summary_parser_counts_mixed_results():
    output = (
        "progress output\n"
        "2 failed, 104 passed, 1 skipped in 1.87s\n"
    )

    assert live_evaluation._parse_pytest_summary(output) == {
        "passed": 104,
        "failed": 2,
        "skipped": 1,
    }


def test_pytest_summary_parser_rejects_missing_summary():
    try:
        live_evaluation._parse_pytest_summary("no summary here")
    except ValueError as exc:
        assert "parseable summary" in str(exc)
    else:
        raise AssertionError("Expected missing pytest summary to fail")


def test_grounding_report_writes_historical_baseline_and_failure_summary(
    tmp_path, monkeypatch
):
    markdown_path = tmp_path / "grounding.md"
    json_path = tmp_path / "grounding.json"
    monkeypatch.setattr(live_evaluation, "GROUNDING_REPORT_PATH", markdown_path)
    monkeypatch.setattr(live_evaluation, "GROUNDING_JSON_PATH", json_path)
    report = {
        "environment": {
            "run_utc": "2026-11-02T00:00:00+00:00",
            "ollama_url": "http://127.0.0.1:11434",
            "installed_models": ["qwen2.5:3b"],
            "runtime": {"max_parallel_models": 1, "keep_alive": "0s"},
        },
        "offline_tests": {"command": "python -m pytest -q", "summary": "1 passed"},
        "baseline": live_evaluation._read_previous_baseline(),
        "root_cause_analysis": ["Verified observation indexing."],
        "changes": [{"file": "agents/graph.py", "change": "Add source facts."}],
        "sequential_overlap_detected": False,
        "agents": [{
            "agent": "monitoring",
            "assigned_model": "qwen2.5:3b",
            "inference_status": "ok",
            "json_schema_valid": True,
            "required_observations": [{"identified": True}],
            "material_unsupported_claims": [],
            "latency_seconds": 9.0,
            "retry_count": 0,
            "overall_result": "PASS",
        }],
        "summary": {
            "total_inference_seconds": 9.0,
            "inference_ok": 1,
            "schema_valid": 1,
            "pass": 1,
            "partial": 0,
            "failed": 0,
            "skipped": 0,
        },
        "safety": {
            "model_config_unchanged": True,
            "persistent_config_enabled": False,
            "models_loaded_after_run": 0,
        },
    }

    live_evaluation._write_grounding_report(report)

    markdown = markdown_path.read_text(encoding="utf-8")
    saved_json = json_path.read_text(encoding="utf-8")
    assert "6.16" in markdown
    assert "9.00" in markdown
    assert "1 PASS, 0 PARTIAL, 0 FAIL, 0 SKIPPED" in markdown
    assert json.loads(saved_json)["baseline"]["run_utc"] == (
        "2026-11-01T21:11:29.548160+00:00"
    )


def test_prompt7_offline_report_tracks_extraction_delivery_without_inference():
    report = live_evaluation._build_prompt7_offline_report({
        "command": "python -m pytest -q",
        "return_code": 0,
        "counts": {"passed": 1, "failed": 0, "skipped": 0},
        "summary": "1 passed, 0 failed, 0 skipped",
    })

    assert report["summary"]["agents_total"] == 6
    assert report["summary"]["required_facts_total"] == 30
    assert report["summary"]["required_facts_extracted"] == 30
    assert report["summary"]["required_facts_delivered"] == 30
    assert report["summary"]["interpretation_completeness_rate"] is None
    assert report["summary"]["live_model_inference"] == "not_run"
    assert all(agent["routing_selected"] for agent in report["agents"])
    assert all(
        agent["evidence_payload_matches_graph"]
        and agent["all_extracted_role_evidence_delivered"]
        for agent in report["agents"]
    )
    security = next(agent for agent in report["agents"] if agent["agent"] == "security")
    assert {item["category"] for item in security["verified_observations"]} <= {
        "security"
    }
    assert report["safety"]["live_inference_executed"] is False
    assert report["safety"]["remediation_executed"] is False


def test_prompt7_markdown_and_json_are_written_from_same_report(tmp_path, monkeypatch):
    markdown_path = tmp_path / "prompt7.md"
    json_path = tmp_path / "prompt7.json"
    monkeypatch.setattr(live_evaluation, "PROMPT7_REPORT_PATH", markdown_path)
    monkeypatch.setattr(live_evaluation, "PROMPT7_JSON_PATH", json_path)
    report = live_evaluation._build_prompt7_offline_report({
        "command": "python -m pytest -q",
        "return_code": 0,
        "counts": {"passed": 12, "failed": 0, "skipped": 1},
        "summary": "12 passed, 0 failed, 1 skipped",
    })

    live_evaluation._write_prompt7_reports(report)

    saved_report = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert saved_report == report
    assert "12 passed, 0 failed, 1 skipped" in markdown
    assert "**Live Ollama inference:** not run" in markdown
    assert "30/30 (100.0%)" in markdown


def test_prompt71_rehydrates_prompt6_evidence_and_existing_graph_inputs(
    tmp_path, monkeypatch
):
    source = live_evaluation._scenario_data()
    report_path = tmp_path / "prompt6.json"
    report_path.write_text(json.dumps({
        "environment": {"run_utc": "2026-11-01T21:00:00+00:00"},
        "agents": [
            {
                "agent": name,
                "scenario_summary": scenario["task"],
                "expected_criteria": scenario["expected_criteria"],
                "original_synthetic_evidence": scenario["evidence"],
            }
            for name, scenario in source.items()
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(live_evaluation, "JSON_REPORT_PATH", report_path)

    scenarios = live_evaluation._prompt6_scenarios_from_report()

    for name in live_evaluation.AGENT_ORDER:
        assert scenarios[name]["evidence"] == source[name]["evidence"]
        assert scenarios[name]["task"] == source[name]["task"]
        assert scenarios[name]["query"] == source[name]["query"]
        assert scenarios[name]["comparison"] == source[name]["comparison"]
        assert scenarios[name]["reference_timestamp"] == (
            live_evaluation.datetime.fromisoformat(
                "2026-11-01T21:00:00+00:00"
            ).timestamp()
        )


def test_prompt71_extraction_counts_stale_facts_but_marks_them_unusable():
    stale = {
        "category": "application_metrics",
        "metric_or_event": "request_rate",
        "status": "stale",
        "evidence_text": '{"status": "ok"}',
        "evidence_id": "id-1",
        "source_path": "prometheus.metrics.request_rate.observations[0]",
    }
    requirement = ("application_metrics", "request_rate", None)

    assert live_evaluation._required_fact_matches(
        [stale], requirement, include_stale=True
    ) == [stale]
    assert live_evaluation._required_fact_matches([stale], requirement) == []


def test_prompt71_separates_hypotheses_from_deterministic_observations():
    categories = live_evaluation._categorize_response(
        {
            "summary": "The metric is 88 percent.",
            "findings": ["A possible cause is resource pressure."],
            "recommended_checks": ["Check the host metrics."],
        },
        [{
            "validation_status": "unverified",
            "reasons": ["unsupported hypothesis"],
            "text": "Possible cause is resource pressure.",
        }],
        [{"detail": "Docker source unavailable"}],
    )

    assert categories["model_interpretations"] == ["The metric is 88 percent."]
    assert categories["hypotheses"] == ["A possible cause is resource pressure."]
    assert categories["recommendations_not_executed"] == ["Check the host metrics."]
    assert categories["verified_observations"] == []
    assert categories["hypothesis_promoted_to_verified"] is False
    assert categories["reported_missing_evidence"] == ["Docker source unavailable"]


def test_prompt71_failure_analysis_identifies_extracted_and_delivered_facts():
    fact = {
        "category": "infrastructure",
        "metric_or_event": "container_health_status",
        "value": "healthy",
        "status": "observed",
        "source_path": "docker.containers[0].health_status",
    }
    entry = {
        "agent": "infrastructure",
        "overall_result": "PARTIAL",
        "missing_observations": ["Healthy state"],
        "deterministic_evidence": {"observations": [fact]},
        "evidence_delivery": {"observations": [fact]},
        "graph_shaped_evidence": {},
        "extraction_completeness": 1.0,
        "delivery_completeness": 1.0,
    }

    failure = live_evaluation._prompt71_failure_analysis(entry, {})[0]

    assert failure["facts_extracted_and_delivered"] is True
    assert failure["facts_delivered"][0]["value"] == "healthy"
    assert "model omission" in failure["interpretation"]


def test_prompt71_grounding_score_is_validator_based_and_handles_no_claims():
    assert live_evaluation._grounding_score({
        "claims": [{"text": "claim"}, {"text": "check"}],
        "material_unsupported_claims": [{"text": "claim"}],
    }) == 0.5
    assert live_evaluation._grounding_score({
        "claims": [],
        "material_unsupported_claims": [],
    }) is None


def test_prompt71_manual_review_keeps_raw_rubric_results_separate():
    scenarios = live_evaluation._scenario_data()
    baseline_agents = []
    current_agents = []
    for name in live_evaluation.AGENT_ORDER:
        criteria = [
            item["requirement"]
            for item in live_evaluation._required_observations(
                name, scenarios[name]
            )
        ]
        baseline_agents.append({
            "agent": name,
            "required_observations": [
                {"requirement": item} for item in criteria
            ],
            "claims": [],
            "analysis": {},
        })
        current_agents.append({
            "agent": name,
            "required_observations": [
                {"requirement": item} for item in criteria
            ],
            "claims": [],
            "analysis": {},
        })
    report = {
        "comparison": {"prompt6_agents": baseline_agents},
        "agents": current_agents,
        "scenarios": {
            "security": {
                "original_synthetic_evidence": scenarios["security"]["evidence"]
            }
        },
        "summary": {"prompt7_unsupported_claims": 0},
    }

    review = live_evaluation._prompt71_manual_review(report)

    assert review["summary"]["prompt6_matched"] == 21
    assert review["summary"]["prompt7_matched"] == 10
    assert review["summary"]["prompt6_average_interpretation_completeness"] == 0.6
    assert review["summary"]["prompt7_average_interpretation_completeness"] == (
        10 / 35
    )
    assert review["summary"]["prompt7_validator_reported_unsupported_claims"] == 0
    security = next(item for item in review["agents"] if item["agent"] == "security")
    assert len(security["prompt7_manual_matched"]) == 5


def test_prompt71_live_entry_captures_deterministic_evidence_with_mocked_model(
    monkeypatch,
):
    observed_evidence = []

    def fake_analyze(agent, task, evidence):
        observed_evidence.append(evidence)
        analysis = {
            "summary": "Observed request rate is 10 requests/second.",
            "findings": [],
            "confidence": 0.8,
            "recommended_checks": [],
        }
        return {
            "status": "ok",
            "agent": agent,
            "model": live_evaluation.EXPECTED_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
            "attempts": [{
                "attempt": 1,
                "status": "ok",
                "done_reason": "stop",
                "total_duration": 500_000_000,
            }],
            "retry": {"attempted": False, "status": "not_needed"},
        }

    monkeypatch.setattr(live_evaluation, "_ollama_processes", lambda _url: {"models": []})
    monkeypatch.setattr(live_evaluation.llm_runtime, "analyze", fake_analyze)
    config = live_evaluation.llm_runtime.load_config()
    config["_installed_models"] = list(live_evaluation.EXPECTED_MODELS.values())
    scenario = live_evaluation._scenario_data()["monitoring"]

    entry, _ = live_evaluation._evaluate_one(
        "monitoring",
        scenario,
        config,
        "http://127.0.0.1:11434",
        None,
        include_prompt7_evidence=True,
    )

    assert entry["inference_status"] == "ok"
    assert entry["json_schema_valid"] is True
    assert entry["ollama_inference_seconds"] == 0.5
    assert entry["extraction_completeness"] == 1
    assert entry["delivery_completeness"] == 1
    assert entry["evidence_delivery"]["all_role_observations_delivered"] is True
    assert observed_evidence[0]["deterministic_evidence"]["role"] == "monitoring"
    assert entry["response_categories"]["verified_observations"]
    assert entry["response_categories"]["hypothesis_promoted_to_verified"] is False


def test_prompt_hash_is_reproducible_for_identical_messages():
    messages = [
        {"role": "system", "content": "synthetic"},
        {"role": "user", "content": '{"evidence":{"value":1}}'},
    ]

    assert live_evaluation._prompt_sha256(messages) == (
        live_evaluation._prompt_sha256(messages)
    )
    assert live_evaluation._prompt_sha256(messages) != (
        live_evaluation._prompt_sha256([
            *messages[:-1],
            {"role": "user", "content": '{"evidence":{"value":2}}'},
        ])
    )


def test_fixture_reference_time_makes_extraction_freshness_deterministic(
    monkeypatch,
):
    scenario = live_evaluation._scenario_data()["monitoring"]
    scenario["reference_timestamp"] = 1001.0
    prometheus = scenario["evidence"]["prometheus"]
    prometheus["timestamp"] = 1000.0
    for metric in prometheus["metrics"].values():
        for observation in metric["observations"]:
            observation["latest_timestamp"] = 1000.0
            for value in observation.get("values", []):
                value["timestamp"] = 1000.0

    def fake_analyze(agent, task, evidence):
        analysis = {
            "summary": "Insufficient evidence to determine additional conditions.",
            "findings": [],
            "confidence": 0.5,
            "recommended_checks": [],
        }
        return {
            "status": "ok",
            "agent": agent,
            "model": live_evaluation.EXPECTED_MODELS[agent],
            "analysis": analysis,
            "raw_content": json.dumps(analysis),
            "attempts": [],
        }

    monkeypatch.setattr(live_evaluation, "_ollama_processes", lambda _url: None)
    monkeypatch.setattr(live_evaluation.llm_runtime, "analyze", fake_analyze)
    config = live_evaluation.llm_runtime.load_config()
    config["_installed_models"] = list(live_evaluation.EXPECTED_MODELS.values())

    first, _ = live_evaluation._evaluate_one(
        "monitoring",
        scenario,
        config,
        "http://127.0.0.1:11434",
        None,
        include_prompt7_evidence=True,
        prompt_version=live_evaluation.PROMPT7_2_VERSION,
    )
    second, _ = live_evaluation._evaluate_one(
        "monitoring",
        scenario,
        config,
        "http://127.0.0.1:11434",
        None,
        include_prompt7_evidence=True,
        prompt_version=live_evaluation.PROMPT7_2_VERSION,
    )

    first_statuses = [
        item["status"] for item in first["deterministic_evidence"]["observations"]
    ]
    second_statuses = [
        item["status"] for item in second["deterministic_evidence"]["observations"]
    ]
    assert first_statuses == second_statuses
    assert first_statuses
    assert set(first_statuses) == {"observed"}
    assert first["reproducibility"]["scenario_reference_timestamp"].endswith("Z")
    assert first["reproducibility"]["prompt_sha256"] == (
        second["reproducibility"]["prompt_sha256"]
    )
    assert first["reproducibility"]["attempt_count"] == 0
    assert first["reproducibility"]["manual_semantic_audit"] == {
        "status": "not_performed",
        "score": None,
    }
    assert "messages" not in first["prompt_diagnostics"]


def test_repeated_runs_aggregate_valid_scores_and_report_failures():
    runs = [
        {
            "agent": "monitoring",
            "scenario_id": "prompt6-monitoring",
            "repetition": 1,
            "inference_status": "ok",
            "json_schema_valid": True,
            "latency_seconds": 2.0,
            "ollama_inference_seconds": 1.0,
            "required_observations": [{"identified": True}],
            "claims": [{"text": "supported"}],
            "material_unsupported_claims": [],
        },
        {
            "agent": "monitoring",
            "scenario_id": "prompt6-monitoring",
            "repetition": 2,
            "inference_status": "ok",
            "json_schema_valid": True,
            "latency_seconds": 4.0,
            "ollama_inference_seconds": 3.0,
            "required_observations": [{"identified": True}],
            "claims": [{"text": "supported"}],
            "material_unsupported_claims": [],
        },
        {
            "agent": "monitoring",
            "scenario_id": "prompt6-monitoring",
            "repetition": 3,
            "inference_status": "unavailable",
            "json_schema_valid": False,
            "latency_seconds": 6.0,
            "ollama_inference_seconds": None,
            "reproducibility": {"failure_reasons": ["Ollama unavailable"]},
        },
    ]

    aggregate = live_evaluation._aggregate_repeated_runs(runs)["per_agent"][
        "monitoring"
    ]

    assert aggregate["run_count"] == 3
    assert aggregate["failed_or_incomplete_count"] == 1
    assert aggregate["failed_or_incomplete_runs"][0]["repetition"] == 3
    assert aggregate["wall_time_seconds"]["mean"] == 4.0
    assert aggregate["wall_time_seconds"]["minimum"] == 2.0
    assert aggregate["wall_time_seconds"]["maximum"] == 6.0
    assert aggregate["wall_time_seconds"]["standard_deviation"] == 2.0
    assert aggregate["ollama_total_duration_seconds"]["excluded_count"] == 1
    assert aggregate["automated_interpretation_score"]["mean"] == 1.0
    assert aggregate["grounding_validator_score"]["mean"] == 1.0
    assert aggregate["manual_semantic_audit_score"]["mean"] is None


def test_repeat_runner_uses_identical_fixtures_in_a_serial_three_pass_loop():
    definitions = live_evaluation._scenario_data()
    scenarios = {
        name: definitions[name] for name in live_evaluation.AGENT_ORDER
    }
    scenarios["negative-control-container-health"] = definitions[
        "negative-control-container-health"
    ]
    calls = []

    def evaluate(agent, scenario, previous_end):
        calls.append((
            scenario["scenario_id"],
            json.dumps(scenario["evidence"], sort_keys=True),
            scenario["reference_timestamp"],
        ))
        return {
            "agent": agent,
            "inference_status": "ok",
            "json_schema_valid": True,
            "no_overlap_with_previous": True,
            "analysis": {
                "summary": (
                    "Cannot establish container health because Docker evidence "
                    "is unavailable."
                ),
                "findings": [],
            } if scenario.get("negative_control") else {},
        }, float(len(calls))

    entries, overlap = live_evaluation._run_repetitions(scenarios, 3, evaluate)

    assert len(entries) == 21
    assert not overlap
    assert [item["repetition"] for item in entries[:7]] == [1] * 7
    assert [item["repetition"] for item in entries[7:14]] == [2] * 7
    assert [item["repetition"] for item in entries[14:]] == [3] * 7
    for scenario_id in scenarios:
        repeated_inputs = [
            item[1:] for item in calls if item[0] == scenario_id
        ]
        assert repeated_inputs[0] == repeated_inputs[1] == repeated_inputs[2]
    control = entries[6]
    assert control["negative_control_score"]["score"] == 1.0
    assert control["negative_control_score"]["unsupported_claims"] == []


def test_repeat_runner_rejects_fewer_than_three_repetitions():
    try:
        live_evaluation._run_repetitions({}, 2, lambda *args: ({}, None))
    except ValueError as exc:
        assert "at least 3 repetitions" in str(exc)
    else:
        raise AssertionError("Prompt 7.2 must enforce three repetitions.")


def test_negative_control_marks_invented_health_restarts_cpu_and_names():
    result = live_evaluation._negative_control_score({
        "summary": (
            "Container checkout-worker-7 is healthy with 0 restarts and 20% CPU. "
            "Container made-up-worker is running."
        ),
        "findings": [],
    })

    assert result["score"] == 0.0
    flagged_categories = {
        category
        for claim in result["unsupported_claims"]
        for category in claim["categories"]
    }
    assert {
        "asserted_container_health_or_status",
        "asserted_restart_count",
        "asserted_cpu_usage",
        "invented_container_name",
    } <= flagged_categories


def test_negative_control_requires_explicit_abstention():
    scenario = live_evaluation._scenario_data()[
        "negative-control-container-health"
    ]
    shaped = live_evaluation.graph._specialist_evidence(
        "infrastructure",
        live_evaluation._routing_state("infrastructure", scenario),
    )
    result = live_evaluation._negative_control_score({
        "summary": "Docker evidence is unavailable; container health cannot be established.",
        "findings": [],
    })

    assert shaped["docker"]["status"] == "unavailable"
    assert result["score"] == 1.0
    assert result["abstention_present"] is True
    assert "checkout-worker-7" not in json.dumps(shaped)


def test_evidence_overlap_diagnostics_measures_raw_verified_and_deterministic_facts():
    evidence = {
        "prometheus": {
            "metrics": {
                "request_rate": {
                    "observations": [{"value": 10, "timestamp": 123.0}]
                }
            }
        },
        "verified_observations": [{
            "statement": "Prometheus request rate is 10 requests/second.",
            "source": "prometheus.metrics.request_rate.observations[0]",
            "timestamp": 123.0,
        }],
        "deterministic_evidence": {
            "observations": [{
                "source_path": "prometheus.metrics.request_rate.observations[0]",
                "value": 10,
                "timestamp": 123.0,
            }]
        },
    }

    result = live_evaluation._evidence_overlap_diagnostics(evidence)

    assert result["raw_source_paths_resolved"] == 1
    assert result["raw_source_value_match_count"] == 1
    assert result["shared_verified_deterministic_source_timestamp_count"] == 1
    assert result["raw_verified_deterministic_overlap_count"] == 1


def test_prompt72_reports_use_one_data_object_and_preserve_historical_reports(
    tmp_path, monkeypatch
):
    historical_dir = tmp_path / "historical"
    historical_dir.mkdir()
    historical_constants = (
        "REPORT_PATH",
        "JSON_REPORT_PATH",
        "GROUNDING_REPORT_PATH",
        "GROUNDING_JSON_PATH",
        "PROMPT7_REPORT_PATH",
        "PROMPT7_JSON_PATH",
        "PROMPT7_1_REPORT_PATH",
        "PROMPT7_1_JSON_PATH",
    )
    historical_paths = []
    for constant in historical_constants:
        path = historical_dir / (constant + ".json")
        if constant == "PROMPT7_1_JSON_PATH":
            path.write_text(
                json.dumps(json.loads(
                    live_evaluation.PROMPT7_1_JSON_PATH.read_text(
                        encoding="utf-8"
                    )
                )),
                encoding="utf-8",
            )
        elif constant == "JSON_REPORT_PATH":
            path.write_text(
                live_evaluation.JSON_REPORT_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            path.write_text("historical\n", encoding="utf-8")
        monkeypatch.setattr(live_evaluation, constant, path)
        historical_paths.append(path)
    markdown_path = tmp_path / "prompt72.md"
    json_path = tmp_path / "prompt72.json"
    plan_path = tmp_path / "plan.md"
    monkeypatch.setattr(live_evaluation, "PROMPT7_2_REPORT_PATH", markdown_path)
    monkeypatch.setattr(live_evaluation, "PROMPT7_2_JSON_PATH", json_path)
    monkeypatch.setattr(live_evaluation, "PROMPT7_2_PLAN_PATH", plan_path)
    before = [path.read_bytes() for path in historical_paths]

    report = live_evaluation._build_prompt7_2_report([{
        "command": "python -m pytest -q",
        "return_code": 0,
        "summary": "12 passed, 0 failed, 0 skipped",
        "counts": {"passed": 12, "failed": 0, "skipped": 0},
    }])
    live_evaluation._write_prompt7_2_reports(report)

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert saved == report
    assert "12 passed, 0 failed, 0 skipped" in markdown
    assert "Live Ollama inference:** not run" in markdown
    assert report["historical_reports_preserved"] is True
    assert report["preflight_configuration"]["persistent_models_enabled"] is False
    assert report["preflight_configuration"]["max_parallel_models"] == 1
    assert report["preflight_configuration"][
        "runtime_matches_prompt6_for_context_and_output"
    ] is True
    assert report["historical_score_baselines"]["automated_interpretation"][
        "prompt_6_0"
    ] == 0.6190476190476191
    assert report["historical_score_baselines"]["automated_interpretation"][
        "prompt_7_1"
    ] == 0.2714285714285714
    assert report["historical_score_baselines"]["grounding_validator"][
        "prompt_6_0"
    ] == 0.9292929292929294
    assert report["historical_score_baselines"]["grounding_validator"][
        "prompt_7_1"
    ] == 0.8694444444444445
    assert report["historical_score_baselines"]["manual_semantic_audit"][
        "prompt_7_1_matched"
    ] == 10
    assert "raw_verified_deterministic_overlap_count" in report[
        "historical_prompt_7_1_observations"
    ]["exact_verified_deterministic_overlap"]
    assert "exact source path and value" in markdown
    assert [path.read_bytes() for path in historical_paths] == before
    assert plan_path.exists()


def test_rubric_equivalence_diagnostic_does_not_change_automated_scores():
    diagnostic = live_evaluation._rubric_equivalence_diagnostic()

    assert diagnostic["requirement"] == "P95 latency"
    assert diagnostic["current_automated_pattern_matches"] is False
    assert "not a human semantic score" in diagnostic["interpretation"]


def test_repeated_evaluation_markdown_and_json_share_the_run_report(
    tmp_path, monkeypatch
):
    markdown_path = tmp_path / "repeated.md"
    json_path = tmp_path / "repeated.json"
    monkeypatch.setattr(
        live_evaluation, "PROMPT7_2_RUN_REPORT_PATH", markdown_path
    )
    monkeypatch.setattr(live_evaluation, "PROMPT7_2_RUN_JSON_PATH", json_path)
    report = live_evaluation._build_prompt7_2_repeated_report(
        [{
            "agent": "monitoring",
            "scenario_id": "prompt6-monitoring",
            "repetition": 1,
            "inference_status": "unavailable",
            "json_schema_valid": False,
            "latency_seconds": 1.0,
            "ollama_inference_seconds": None,
            "attempts": [],
        }],
        run_utc="2026-11-02T00:00:00+00:00",
        repetitions=3,
        sequential_overlap_detected=False,
    )

    live_evaluation._write_prompt7_2_repeated_reports(report)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Runs:** 1; successes: 0; failures: 1" in markdown
    assert "quality failures: 0" in markdown
    assert "measurement_unavailable" in markdown
    assert "Failed/incomplete" in markdown
    assert "not performed" in markdown


def test_prompt71_reports_are_written_from_one_result_object(tmp_path, monkeypatch):
    markdown_path = tmp_path / "prompt7_1.md"
    json_path = tmp_path / "prompt7_1.json"
    monkeypatch.setattr(live_evaluation, "PROMPT7_1_REPORT_PATH", markdown_path)
    monkeypatch.setattr(live_evaluation, "PROMPT7_1_JSON_PATH", json_path)
    agent = {
        "agent": "monitoring",
        "assigned_model": "qwen2.5:3b",
        "overall_result": "PASS",
        "required_fact_results": [{
            "extracted": True,
            "delivered": True,
            "usable": True,
        }],
        "required_observations": [{"identified": True}],
        "claims": [{"text": "observed value"}],
        "material_unsupported_claims": [],
        "ollama_inference_seconds": 1.25,
        "latency_seconds": 1.5,
        "retry_count": 0,
        "json_schema_valid": True,
        "failure_analysis": [],
    }
    comparison_agent = {
        "agent": "monitoring",
        "prompt7_extraction_completeness": 1.0,
        "prompt7_delivery_completeness": 1.0,
        "prompt6_interpretation": "1/1 (100.0%)",
        "prompt7_interpretation": "1/1 (100.0%)",
        "interpretation_change": "+0.0%",
        "prompt6_grounding": "100.0%",
        "prompt7_grounding": "100.0%",
        "prompt6_unsupported_claims": 0,
        "prompt7_unsupported_claims": 0,
    }
    report = {
        "environment": {
            "run_utc": "2026-11-02T00:00:00+00:00",
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_version": "0.0",
            "installed_models": ["qwen2.5:3b"],
            "missing_models": [],
            "models_loaded_before": 0,
            "models_loaded_after": 0,
            "runtime": {"max_parallel_models": 1},
        },
        "offline_tests": {"summary": "128 passed, 0 failed, 0 skipped"},
        "comparison": {
            "fixture_source": "reports/six_agent_live_evaluation.json",
            "agents": [comparison_agent],
            "prompt6_agents": [{"agent": "monitoring"}],
        },
        "summary": {
            "prompt6_average_interpretation_completeness": 1.0,
            "prompt7_average_interpretation_completeness": 1.0,
            "prompt6_average_grounding_score": 1.0,
            "prompt7_average_grounding_score": 1.0,
            "prompt6_unsupported_claims": 0,
            "prompt7_unsupported_claims": 0,
            "prompt6_missed_criteria": 0,
            "prompt7_missed_criteria": 0,
            "prompt6_schema_valid": 1,
            "prompt7_schema_valid": 1,
            "prompt6_inference_seconds": 1.0,
            "prompt7_inference_seconds": 1.25,
            "prompt7_total_wall_seconds": 1.5,
            "prompt7_total_evaluation_seconds": 4.0,
        },
        "agents": [agent],
        "safety": {
            "persistent_enabled": False,
            "runtime_settings_match_prompt6": True,
            "config_unchanged": True,
            "operational_actions_not_executed": True,
        },
        "sequential_overlap_detected": False,
        "limitations": ["Scoring is heuristic."],
    }

    live_evaluation._write_prompt71_reports(report)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "1.25" in markdown
    assert "not measured" in markdown
    assert "Grounding score is a validator-based ratio" in markdown
