"""Deterministic offline normalization and deduplication of CI/CD and security scanner reports.

Supported scanner formats:
- pip-audit (Python dependency vulnerabilities)
- npm audit (Node.js dependency vulnerabilities)
- Trivy image scan (Container image OS and package vulnerabilities)
- Trivy config scan (Infrastructure and Dockerfile misconfigurations)
- Gitleaks (Committed secrets and token detection)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agents.untrusted_text import (
    sanitize_identifier,
    sanitize_location,
    sanitize_text,
    MAX_PACKAGE_LENGTH,
    MAX_VERSION_LENGTH,
)

MAX_INPUT_BYTES = 5 * 1024 * 1024  # 5 MB maximum scanner input size

ALLOWED_CATEGORIES = {
    "dependency_vulnerability",
    "image_vulnerability",
    "misconfiguration",
    "secret",
}

ALLOWED_SEVERITIES = {
    "critical",
    "high",
    "medium",
    "low",
    "unknown",
}

SEVERITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "unknown": 0,
}

ALLOWED_STATUSES = {
    "clean",
    "findings",
    "scanner_error",
    "not_run",
    "stale",
    "unavailable",
}

SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "moderate": "medium",
    "medium": "medium",
    "low": "low",
    "info": "unknown",
    "unknown": "unknown",
}


def _normalize_severity(val: Any) -> str:
    """Normalize severity string to allowed closed vocabulary."""
    if not isinstance(val, str):
        return "unknown"
    return SEVERITY_MAP.get(val.strip().lower(), "unknown")


def compute_finding_id(
    category: str,
    identifier: str,
    package: str | None,
    version: str | None,
    location: str | None,
) -> str:
    """Generate a stable, deterministic SHA-256 finding identifier."""
    canon_cat = (category or "").strip().lower()
    canon_id = (identifier or "").strip().upper()
    canon_pkg = (package or "").strip().lower()
    canon_ver = (version or "").strip()
    canon_loc = (location or "").strip()
    identity = f"{canon_cat}:{canon_id}:{canon_pkg}:{canon_ver}:{canon_loc}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _extract_canonical_cve_or_id(primary_id: str, aliases: list[str]) -> str:
    """Select the canonical CVE if available, else primary ID."""
    all_ids = [primary_id] + aliases
    cves = [ident.strip().upper() for ident in all_ids if ident and ident.strip().upper().startswith("CVE-")]
    if cves:
        return sorted(cves)[0]
    return primary_id.strip()


def _load_and_validate_json(raw_input: Any) -> tuple[Any | None, str | None, str]:
    """Validate input size and structure, returning (parsed_data, error_detail, status)."""
    if raw_input is None:
        return None, "Scanner report not provided or missing", "not_run"

    # If Path object or string that points to existing file, read it safely
    if isinstance(raw_input, Path) or (
        isinstance(raw_input, str) and len(raw_input) < 1000 and Path(raw_input).is_file()
    ):
        try:
            path = Path(raw_input)
            size = path.stat().st_size
            if size > MAX_INPUT_BYTES:
                return (
                    None,
                    f"Report file exceeds maximum allowed size of {MAX_INPUT_BYTES} bytes ({size} bytes)",
                    "scanner_error",
                )
            content_bytes = path.read_bytes()
            if len(content_bytes) > MAX_INPUT_BYTES:
                return None, "File content exceeds 5 MB limit", "scanner_error"
            try:
                parsed = json.loads(content_bytes.decode("utf-8"))
                return parsed, None, "ok"
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return None, f"Malformed JSON in file: {exc}", "scanner_error"
        except OSError as exc:
            return None, f"Failed to read scanner file: {exc}", "scanner_error"

    if isinstance(raw_input, (bytes, bytearray)):
        if len(raw_input) > MAX_INPUT_BYTES:
            return (
                None,
                f"Input exceeds maximum allowed size of {MAX_INPUT_BYTES} bytes ({len(raw_input)} bytes)",
                "scanner_error",
            )
        try:
            parsed = json.loads(raw_input.decode("utf-8"))
            return parsed, None, "ok"
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, f"Malformed JSON payload: {exc}", "scanner_error"

    if isinstance(raw_input, str):
        encoded_len = len(raw_input.encode("utf-8"))
        if encoded_len > MAX_INPUT_BYTES:
            return (
                None,
                f"Input exceeds maximum allowed size of {MAX_INPUT_BYTES} bytes ({encoded_len} bytes)",
                "scanner_error",
            )
        try:
            parsed = json.loads(raw_input)
            return parsed, None, "ok"
        except json.JSONDecodeError as exc:
            return None, f"Malformed JSON string: {exc}", "scanner_error"

    if isinstance(raw_input, (dict, list)):
        return raw_input, None, "ok"

    return None, f"Unsupported input type: {type(raw_input).__name__}", "scanner_error"


def parse_pip_audit(content: Any) -> dict[str, Any]:
    """Parse pip-audit JSON report deterministically into normalized findings."""
    data, error, status = _load_and_validate_json(content)
    if error or status != "ok":
        return {
            "scanner": "pip-audit",
            "status": status,
            "error": error,
            "findings": [],
        }

    # Structure validation: pip-audit outputs either {"dependencies": [...]} or a list of dependency dicts
    deps = None
    if isinstance(data, dict):
        deps = data.get("dependencies")
        if deps is None and "fixes" in data:
            deps = []  # Some pip-audit variants report fixes
    elif isinstance(data, list):
        deps = data

    if deps is None or not isinstance(deps, list):
        return {
            "scanner": "pip-audit",
            "status": "scanner_error",
            "error": "Invalid pip-audit structure: expected 'dependencies' list or top-level list",
            "findings": [],
        }

    findings: list[dict[str, Any]] = []
    for dep in deps:
        if not isinstance(dep, dict):
            return {
                "scanner": "pip-audit",
                "status": "scanner_error",
                "error": "Invalid pip-audit structure: dependency record must be an object",
                "findings": [],
            }
        pkg_name = sanitize_text(dep.get("name"), max_length=MAX_PACKAGE_LENGTH)
        pkg_version = sanitize_text(dep.get("version"), max_length=MAX_VERSION_LENGTH)
        vulns = dep.get("vulns", [])
        if not isinstance(vulns, list):
            continue

        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            vuln_id = sanitize_identifier(vuln.get("id", ""))
            if not vuln_id:
                continue

            raw_aliases = vuln.get("aliases", [])
            aliases = [
                sanitize_identifier(a)
                for a in raw_aliases
                if isinstance(a, str) and sanitize_identifier(a)
            ] if isinstance(raw_aliases, list) else []

            raw_fixes = vuln.get("fix_versions", [])
            fixed_versions = [
                sanitize_text(f, max_length=MAX_VERSION_LENGTH)
                for f in raw_fixes
                if isinstance(f, str) and f.strip()
            ] if isinstance(raw_fixes, list) else []

            canonical_id = _extract_canonical_cve_or_id(vuln_id, aliases)
            finding_id = compute_finding_id(
                category="dependency_vulnerability",
                identifier=canonical_id,
                package=pkg_name,
                version=pkg_version,
                location="requirements.txt",
            )

            desc = sanitize_text(vuln.get("description", ""))
            title = desc if desc else f"Vulnerability {vuln_id} in {pkg_name}"
            remediation = (
                f"Upgrade {pkg_name} to {', '.join(fixed_versions)}"
                if fixed_versions
                else f"Upgrade {pkg_name} to a non-vulnerable version"
            )

            findings.append({
                "finding_id": finding_id,
                "scanners": ["pip-audit"],
                "category": "dependency_vulnerability",
                "severity": "unknown",  # pip-audit does not provide severity; never guess
                "identifier": vuln_id,
                "aliases": sorted(list(set(aliases))),
                "package": pkg_name,
                "installed_version": pkg_version,
                "fixed_versions": fixed_versions,
                "location": "requirements.txt",
                "title": title,
                "remediation_hint": remediation,
            })

    return {
        "scanner": "pip-audit",
        "status": "findings" if findings else "clean",
        "error": None,
        "findings": findings,
    }


def parse_npm_audit(content: Any) -> dict[str, Any]:
    """Parse npm audit JSON report (v2/v7+ and v6) into normalized findings."""
    data, error, status = _load_and_validate_json(content)
    if error or status != "ok":
        return {
            "scanner": "npm-audit",
            "status": status,
            "error": error,
            "findings": [],
        }

    if not isinstance(data, dict):
        return {
            "scanner": "npm-audit",
            "status": "scanner_error",
            "error": "Invalid npm audit structure: root must be a JSON object",
            "findings": [],
        }

    findings: list[dict[str, Any]] = []

    # v2 audit report format
    if "vulnerabilities" in data and isinstance(data["vulnerabilities"], dict):
        for pkg_name, entry in data["vulnerabilities"].items():
            if not isinstance(entry, dict):
                continue
            pkg = sanitize_text(entry.get("name") or pkg_name, max_length=MAX_PACKAGE_LENGTH)
            severity = _normalize_severity(entry.get("severity"))

            nodes = entry.get("nodes", [])
            location = (
                sanitize_location(nodes[0])
                if isinstance(nodes, list) and nodes
                else "package.json"
            )

            fix_info = entry.get("fixAvailable")
            fixed_versions: list[str] = []
            if isinstance(fix_info, dict) and fix_info.get("version"):
                fixed_versions.append(sanitize_text(fix_info["version"], max_length=MAX_VERSION_LENGTH))

            via = entry.get("via", [])
            if isinstance(via, list):
                for item in via:
                    if isinstance(item, dict):
                        vuln_title = sanitize_text(item.get("title", ""))
                        url = str(item.get("url", ""))
                        # Extract identifier from advisory URL or use title/source
                        advisory_id = ""
                        aliases = []
                        if "GHSA-" in url:
                            ghsa_part = url.split("/")[-1]
                            advisory_id = sanitize_identifier(ghsa_part)
                        elif item.get("source"):
                            advisory_id = f"NPM-{item.get('source')}"
                        else:
                            advisory_id = sanitize_identifier(item.get("name", pkg))

                        cwe_list = item.get("cwe", [])
                        if isinstance(cwe_list, list):
                            aliases.extend([sanitize_identifier(c) for c in cwe_list if isinstance(c, str)])

                        item_sev = _normalize_severity(item.get("severity") or severity)
                        canonical_id = _extract_canonical_cve_or_id(advisory_id, aliases)
                        finding_id = compute_finding_id(
                            category="dependency_vulnerability",
                            identifier=canonical_id,
                            package=pkg,
                            version=sanitize_text(entry.get("range", "")),
                            location=location,
                        )

                        remediation = (
                            f"Update {pkg} to {', '.join(fixed_versions)}"
                            if fixed_versions
                            else f"Run npm audit fix or update {pkg}"
                        )

                        findings.append({
                            "finding_id": finding_id,
                            "scanners": ["npm-audit"],
                            "category": "dependency_vulnerability",
                            "severity": item_sev,
                            "identifier": advisory_id,
                            "aliases": sorted(list(set(aliases))),
                            "package": pkg,
                            "installed_version": sanitize_text(entry.get("range", "")),
                            "fixed_versions": fixed_versions,
                            "location": location,
                            "title": vuln_title or f"Vulnerability in {pkg}",
                            "remediation_hint": remediation,
                        })

    # Legacy v6 format
    elif "advisories" in data and isinstance(data["advisories"], dict):
        for adv_id, adv in data["advisories"].items():
            if not isinstance(adv, dict):
                continue
            pkg = sanitize_text(adv.get("module_name", ""), max_length=MAX_PACKAGE_LENGTH)
            severity = _normalize_severity(adv.get("severity"))
            cves = adv.get("cves", [])
            aliases = [sanitize_identifier(c) for c in cves if isinstance(c, str)] if isinstance(cves, list) else []
            identifier = sanitize_identifier(adv.get("github_advisory_id") or (aliases[0] if aliases else f"NPM-{adv_id}"))
            canonical_id = _extract_canonical_cve_or_id(identifier, aliases)
            pat_version = sanitize_text(adv.get("patched_versions", ""), max_length=MAX_VERSION_LENGTH)
            fixed_versions = [pat_version] if pat_version else []

            finding_id = compute_finding_id(
                category="dependency_vulnerability",
                identifier=canonical_id,
                package=pkg,
                version=sanitize_text(adv.get("vulnerable_versions", "")),
                location="package.json",
            )

            findings.append({
                "finding_id": finding_id,
                "scanners": ["npm-audit"],
                "category": "dependency_vulnerability",
                "severity": severity,
                "identifier": identifier,
                "aliases": sorted(list(set(aliases))),
                "package": pkg,
                "installed_version": sanitize_text(adv.get("vulnerable_versions", "")),
                "fixed_versions": fixed_versions,
                "location": "package.json",
                "title": sanitize_text(adv.get("title", "")),
                "remediation_hint": sanitize_text(adv.get("recommendation", "")),
            })
    elif "metadata" in data and data.get("metadata", {}).get("vulnerabilities", {}).get("total", 0) == 0:
        # Valid empty npm audit report
        pass
    else:
        return {
            "scanner": "npm-audit",
            "status": "scanner_error",
            "error": "Invalid npm audit structure: missing vulnerabilities or advisories object",
            "findings": [],
        }

    return {
        "scanner": "npm-audit",
        "status": "findings" if findings else "clean",
        "error": None,
        "findings": findings,
    }


def parse_trivy_image(content: Any) -> dict[str, Any]:
    """Parse Trivy container image scan JSON report into normalized findings."""
    data, error, status = _load_and_validate_json(content)
    if error or status != "ok":
        return {
            "scanner": "trivy-image",
            "status": status,
            "error": error,
            "findings": [],
        }

    if not isinstance(data, dict):
        return {
            "scanner": "trivy-image",
            "status": "scanner_error",
            "error": "Invalid Trivy image structure: root must be a JSON object",
            "findings": [],
        }

    results = data.get("Results")
    if results is None:
        return {
            "scanner": "trivy-image",
            "status": "scanner_error",
            "error": "Invalid Trivy image structure: missing 'Results' field",
            "findings": [],
        }
    if not isinstance(results, list):
        return {
            "scanner": "trivy-image",
            "status": "scanner_error",
            "error": "Invalid Trivy image structure: 'Results' must be an array",
            "findings": [],
        }

    findings: list[dict[str, Any]] = []
    for res in results:
        if not isinstance(res, dict):
            continue
        target = sanitize_location(res.get("Target", "container_image"))
        res_class = str(res.get("Class", "")).lower()

        vulns = res.get("Vulnerabilities", [])
        if vulns is None:
            continue
        if not isinstance(vulns, list):
            continue

        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            vuln_id = sanitize_identifier(vuln.get("VulnerabilityID", ""))
            if not vuln_id:
                continue

            pkg_name = sanitize_text(vuln.get("PkgName", ""), max_length=MAX_PACKAGE_LENGTH)
            installed_ver = sanitize_text(vuln.get("InstalledVersion", ""), max_length=MAX_VERSION_LENGTH)
            fixed_ver = vuln.get("FixedVersion")
            fixed_versions = (
                [sanitize_text(fixed_ver, max_length=MAX_VERSION_LENGTH)]
                if fixed_ver and isinstance(fixed_ver, str)
                else []
            )

            severity = _normalize_severity(vuln.get("Severity"))
            category = "dependency_vulnerability" if res_class == "lang-pkgs" else "image_vulnerability"

            # References and aliases
            refs = vuln.get("References", [])
            aliases: list[str] = []
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str):
                        for part in ref.split("/"):
                            if part.startswith("GHSA-") or part.startswith("CVE-"):
                                aliases.append(sanitize_identifier(part))

            canonical_id = _extract_canonical_cve_or_id(vuln_id, aliases)
            # Normalize target location for consistent cross-scanner matching if language package
            norm_location = "requirements.txt" if ("requirements" in target.lower() and res_class == "lang-pkgs") else target

            finding_id = compute_finding_id(
                category=category,
                identifier=canonical_id,
                package=pkg_name,
                version=installed_ver,
                location=norm_location,
            )

            title = sanitize_text(vuln.get("Title") or vuln.get("Description") or f"{vuln_id} in {pkg_name}")
            remediation = (
                f"Upgrade {pkg_name} to {fixed_versions[0]}"
                if fixed_versions
                else f"Update {pkg_name} to a patched version"
            )

            findings.append({
                "finding_id": finding_id,
                "scanners": ["trivy"],
                "category": category,
                "severity": severity,
                "identifier": vuln_id,
                "aliases": sorted(list(set(aliases))),
                "package": pkg_name,
                "installed_version": installed_ver,
                "fixed_versions": fixed_versions,
                "location": norm_location,
                "title": title,
                "remediation_hint": remediation,
            })

    return {
        "scanner": "trivy-image",
        "status": "findings" if findings else "clean",
        "error": None,
        "findings": findings,
    }


def parse_trivy_config(content: Any) -> dict[str, Any]:
    """Parse Trivy configuration scan JSON report into normalized misconfiguration findings."""
    data, error, status = _load_and_validate_json(content)
    if error or status != "ok":
        return {
            "scanner": "trivy-config",
            "status": status,
            "error": error,
            "findings": [],
        }

    if not isinstance(data, dict):
        return {
            "scanner": "trivy-config",
            "status": "scanner_error",
            "error": "Invalid Trivy config structure: root must be a JSON object",
            "findings": [],
        }

    results = data.get("Results")
    if results is None:
        return {
            "scanner": "trivy-config",
            "status": "scanner_error",
            "error": "Invalid Trivy config structure: missing 'Results' field",
            "findings": [],
        }
    if not isinstance(results, list):
        return {
            "scanner": "trivy-config",
            "status": "scanner_error",
            "error": "Invalid Trivy config structure: 'Results' must be an array",
            "findings": [],
        }

    findings: list[dict[str, Any]] = []
    for res in results:
        if not isinstance(res, dict):
            continue
        target = sanitize_location(res.get("Target", "config"))
        misconfigs = res.get("Misconfigurations", [])
        if misconfigs is None or not isinstance(misconfigs, list):
            continue

        for mis in misconfigs:
            if not isinstance(mis, dict):
                continue
            mis_id = sanitize_identifier(mis.get("ID") or mis.get("AVDID") or "")
            if not mis_id:
                continue

            avd_id = sanitize_identifier(mis.get("AVDID", ""))
            aliases = [avd_id] if avd_id and avd_id != mis_id else []
            severity = _normalize_severity(mis.get("Severity"))
            title = sanitize_text(mis.get("Title") or mis.get("Description") or mis_id)
            remediation = sanitize_text(mis.get("Resolution") or mis.get("Message") or "Remediate configuration defect.")

            finding_id = compute_finding_id(
                category="misconfiguration",
                identifier=mis_id,
                package=None,
                version=None,
                location=target,
            )

            findings.append({
                "finding_id": finding_id,
                "scanners": ["trivy"],
                "category": "misconfiguration",
                "severity": severity,
                "identifier": mis_id,
                "aliases": aliases,
                "package": None,
                "installed_version": None,
                "fixed_versions": [],
                "location": target,
                "title": title,
                "remediation_hint": remediation,
            })

    return {
        "scanner": "trivy-config",
        "status": "findings" if findings else "clean",
        "error": None,
        "findings": findings,
    }


def parse_gitleaks(content: Any) -> dict[str, Any]:
    """Parse Gitleaks JSON report. Never output raw Secret or Match values."""
    data, error, status = _load_and_validate_json(content)
    if error or status != "ok":
        return {
            "scanner": "gitleaks",
            "status": status,
            "error": error,
            "findings": [],
        }

    if not isinstance(data, list):
        return {
            "scanner": "gitleaks",
            "status": "scanner_error",
            "error": "Invalid Gitleaks structure: root must be a JSON array",
            "findings": [],
        }

    findings: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            return {
                "scanner": "gitleaks",
                "status": "scanner_error",
                "error": "Invalid Gitleaks item: elements must be JSON objects",
                "findings": [],
            }

        rule_id = sanitize_identifier(item.get("RuleID", "detected-secret"))
        file_path = sanitize_location(item.get("File", "unknown"))
        start_line = item.get("StartLine", 0)
        location = f"{file_path}:{start_line}"
        desc = sanitize_text(item.get("Description", "Detected sensitive credential or secret"))

        finding_id = compute_finding_id(
            category="secret",
            identifier=rule_id,
            package=None,
            version=None,
            location=location,
        )

        severity = _normalize_severity(item.get("Severity")) if "Severity" in item else "unknown"

        # NOTE: Gitleaks Secret and Match are NEVER accessed or copied into normalized findings.
        findings.append({
            "finding_id": finding_id,
            "scanners": ["gitleaks"],
            "category": "secret",
            "severity": severity,  # Do not falsely attribute severity if source does not provide it
            "identifier": rule_id,
            "aliases": [],
            "package": None,
            "installed_version": None,
            "fixed_versions": [],
            "location": location,
            "title": desc,
            "remediation_hint": "Revoke and rotate the exposed secret immediately, and remove from git history.",
        })

    return {
        "scanner": "gitleaks",
        "status": "findings" if findings else "clean",
        "error": None,
        "findings": findings,
    }


def are_findings_equivalent(f1: dict[str, Any], f2: dict[str, Any]) -> bool:
    """Check if two findings represent the same issue across scanners."""
    if f1.get("category") != f2.get("category"):
        return False

    # For misconfigurations and secrets, require identical identifier and location
    if f1.get("category") in {"misconfiguration", "secret"}:
        return (
            f1.get("identifier") == f2.get("identifier")
            and f1.get("location") == f2.get("location")
        )

    # For vulnerabilities: require same package (case-insensitive)
    pkg1 = (f1.get("package") or "").strip().lower()
    pkg2 = (f2.get("package") or "").strip().lower()
    if not pkg1 or not pkg2 or pkg1 != pkg2:
        return False

    # Check identifier equivalence: direct match or overlap in aliases
    ids1 = {f1.get("identifier", "").upper()} | {a.upper() for a in f1.get("aliases", [])}
    ids2 = {f2.get("identifier", "").upper()} | {a.upper() for a in f2.get("aliases", [])}
    ids1.discard("")
    ids2.discard("")

    if not (ids1 & ids2):
        return False

    # If installed versions are both present and conflicting, don't merge
    v1 = (f1.get("installed_version") or "").strip()
    v2 = (f2.get("installed_version") or "").strip()
    if v1 and v2 and v1 != v2:
        return False

    return True


def merge_two_findings(f1: dict[str, Any], f2: dict[str, Any]) -> dict[str, Any]:
    """Merge two equivalent findings across scanners."""
    # Scanners union
    scanners = sorted(list(set(f1.get("scanners", []) + f2.get("scanners", []))))

    # Identifiers & aliases
    all_identifiers = list(
        {f1.get("identifier", "")} | set(f1.get("aliases", [])) |
        {f2.get("identifier", "")} | set(f2.get("aliases", []))
    )
    all_identifiers = [i for i in all_identifiers if i]
    canonical_id = _extract_canonical_cve_or_id(f1.get("identifier", ""), all_identifiers)
    aliases = sorted([i for i in all_identifiers if i != canonical_id])

    # Severity: pick highest severity
    sev1 = f1.get("severity", "unknown")
    sev2 = f2.get("severity", "unknown")
    rank1 = SEVERITY_ORDER.get(sev1, 0)
    rank2 = SEVERITY_ORDER.get(sev2, 0)
    severity = sev1 if rank1 >= rank2 else sev2

    # Fixed versions union
    fixed_versions = sorted(list(set(f1.get("fixed_versions", []) + f2.get("fixed_versions", []))))

    # Title & remediation: prefer non-null / longer
    title = f1.get("title") if (f1.get("title") and len(str(f1.get("title"))) >= len(str(f2.get("title") or ""))) else f2.get("title")
    remediation = f1.get("remediation_hint") or f2.get("remediation_hint")
    package = f1.get("package") or f2.get("package")
    installed_ver = f1.get("installed_version") or f2.get("installed_version")
    location = f1.get("location") or f2.get("location")

    finding_id = compute_finding_id(
        category=f1["category"],
        identifier=canonical_id,
        package=package,
        version=installed_ver,
        location=location,
    )

    return {
        "finding_id": finding_id,
        "scanners": scanners,
        "category": f1["category"],
        "severity": severity,
        "identifier": canonical_id,
        "aliases": aliases,
        "package": package,
        "installed_version": installed_ver,
        "fixed_versions": fixed_versions,
        "location": location,
        "title": title,
        "remediation_hint": remediation,
    }


def deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate equivalent findings across all scanners deterministically."""
    merged: list[dict[str, Any]] = []
    for item in findings:
        matched = False
        for i, existing in enumerate(merged):
            if are_findings_equivalent(existing, item):
                merged[i] = merge_two_findings(existing, item)
                matched = True
                break
        if not matched:
            merged.append(dict(item))

    # Sort deterministically by finding_id
    merged.sort(key=lambda x: str(x.get("finding_id", "")))
    return merged


def normalize_security_scans(
    reports: dict[str, Any],
    *,
    is_stale: bool = False,
    is_unavailable: bool = False,
) -> dict[str, Any]:
    """Parse, normalize, and deduplicate findings across all supported security scanners.

    Accepts a dictionary mapping scanner keys to report content, e.g.:
      {
        "pip_audit": content,
        "npm_audit": content,
        "trivy_image": content,
        "trivy_config": content,
        "gitleaks": content,
      }
    """
    parsers = {
        "pip_audit": parse_pip_audit,
        "npm_audit": parse_npm_audit,
        "trivy_image": parse_trivy_image,
        "trivy_config": parse_trivy_config,
        "gitleaks": parse_gitleaks,
    }

    scanners_status: dict[str, Any] = {}
    raw_findings: list[dict[str, Any]] = []
    has_scanner_error = False
    all_not_run = True

    for key, parser_fn in parsers.items():
        content = reports.get(key)
        res = parser_fn(content)
        status = res["status"]
        scanners_status[key] = {
            "status": status,
            "finding_count": len(res.get("findings", [])),
            "error": res.get("error"),
        }
        if status != "not_run":
            all_not_run = False
        if status == "scanner_error":
            has_scanner_error = True
        raw_findings.extend(res.get("findings", []))

    deduped_findings = deduplicate_findings(raw_findings)

    # Determine overall status
    if is_unavailable:
        overall_status = "unavailable"
    elif is_stale:
        overall_status = "stale"
    elif all_not_run:
        overall_status = "not_run"
    elif has_scanner_error and not deduped_findings:
        overall_status = "scanner_error"
    elif deduped_findings:
        overall_status = "findings"
    elif has_scanner_error:
        overall_status = "scanner_error"
    else:
        overall_status = "clean"

    # Compute summary
    summary = {
        "total_findings": len(deduped_findings),
        "by_severity": {sev: 0 for sev in sorted(ALLOWED_SEVERITIES)},
        "by_category": {cat: 0 for cat in sorted(ALLOWED_CATEGORIES)},
    }
    for f in deduped_findings:
        sev = f.get("severity", "unknown")
        cat = f.get("category", "")
        if sev in summary["by_severity"]:
            summary["by_severity"][sev] += 1
        if cat in summary["by_category"]:
            summary["by_category"][cat] += 1

    return {
        "status": overall_status,
        "scanners": scanners_status,
        "summary": summary,
        "findings": deduped_findings,
    }
