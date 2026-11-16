"""Optimized client to synchronize fault injection, deployments, and telemetry with target app."""
from __future__ import annotations

import logging
import os
import time
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("remote_app")

# Global pooled session for persistent keep-alive connections
_SESSION: requests.Session | None = None
_CACHE_REMOTE_INFO: dict[str, Any] | None = None
_CACHE_REMOTE_TS: float = 0.0
_CACHE_TTL_SECONDS = 4.0


def get_http_session() -> requests.Session:
    """Return a shared HTTP session configured with connection pooling and keep-alive."""
    global _SESSION
    if _SESSION is None:
        session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": "DevOps-MultiAgent-System/2.0"})
        _SESSION = session
    return _SESSION


def get_target_app_url() -> str:
    return os.getenv("DEVOPS_APP_URL", "http://127.0.0.1:8100").rstrip("/")


def remote_deploy(version: str, bug: bool = False) -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/deploy", params={"version": version, "bug": bug}, timeout=4.0)
        logger.info("Synchronized deploy v%s (bug=%s) to %s -> %s", version, bug, url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote deploy to %s failed: %s", url, exc)
        return None


def remote_rollback() -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/rollback", timeout=4.0)
        logger.info("Synchronized rollback to %s -> %s", url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote rollback to %s failed: %s", url, exc)
        return None


def remote_inject_latency(seconds: float) -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/fault/latency", params={"seconds": seconds}, timeout=4.0)
        logger.info("Synchronized fault latency %.2fs to %s -> %s", seconds, url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote inject latency to %s failed: %s", url, exc)
        return None


def remote_inject_crash(active: bool = True, message: str = "Unhandled runtime crash in eCommerce service") -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/fault/crash", params={"active": active, "message": message}, timeout=4.0)
        logger.info("Synchronized crash mode active=%s to %s -> %s", active, url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote inject crash to %s failed: %s", url, exc)
        return None


def remote_stress_cpu(duration_seconds: int = 15, num_threads: int = 2) -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/fault/cpu", params={"duration_seconds": duration_seconds, "num_threads": num_threads}, timeout=4.0)
        logger.info("Synchronized CPU stress to %s -> %s", url, resp.status_code)
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote stress cpu to %s failed: %s", url, exc)
        return None


def remote_stress_memory(megabytes: int = 150, duration_seconds: int = 15) -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/fault/memory", params={"megabytes": megabytes, "duration_seconds": duration_seconds}, timeout=4.0)
        logger.info("Synchronized memory stress to %s -> %s", url, resp.status_code)
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote stress memory to %s failed: %s", url, exc)
        return None


def remote_reset_faults() -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.post(f"{url}/admin/fault/reset", timeout=4.0)
        logger.info("Synchronized reset faults to %s -> %s", url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote reset faults on %s failed: %s", url, exc)
        return None


def remote_fault_status() -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.get(f"{url}/admin/fault/status", timeout=4.0)
        return resp.json() if resp.ok else None
    except Exception as exc:
        return None


def remote_deploy_feature(
    op: str,
    code_snippet: str,
    feature_name: str | None = None,
    version: str | None = None,
) -> dict[str, Any] | None:
    url = get_target_app_url()
    session = get_http_session()
    try:
        payload = {
            "op": op,
            "code_snippet": code_snippet,
            "feature_name": feature_name,
            "version": version,
        }
        resp = session.post(f"{url}/admin/features/deploy", json=payload, timeout=5.0)
        logger.info("Synchronized feature %s deployment to %s -> %s", op, url, resp.status_code)
        _invalidate_cache()
        return resp.json() if resp.ok else None
    except Exception as exc:
        logger.warning("Remote deploy feature to %s failed: %s", url, exc)
        return None


def _invalidate_cache():
    global _CACHE_REMOTE_INFO, _CACHE_REMOTE_TS
    _CACHE_REMOTE_INFO = None
    _CACHE_REMOTE_TS = 0.0


def get_remote_app_info() -> dict[str, Any]:
    """Retrieve remote application health telemetry with short-lived TTL caching."""
    global _CACHE_REMOTE_INFO, _CACHE_REMOTE_TS
    now = time.time()
    if _CACHE_REMOTE_INFO is not None and (now - _CACHE_REMOTE_TS) < _CACHE_TTL_SECONDS:
        return dict(_CACHE_REMOTE_INFO)

    url = get_target_app_url()
    session = get_http_session()
    try:
        resp = session.get(f"{url}/health", timeout=3.0)
        if resp.ok:
            data = resp.json()
            info = {
                "status": "online",
                "url": url,
                "version": data.get("version", "1.0"),
                "active_operations": data.get("operations", []),
                "total_operations": data.get("active_operations", len(data.get("operations", []))),
                "catalog_size": data.get("catalog_size", 0),
                "orders_count": data.get("orders_count", 0),
            }
            _CACHE_REMOTE_INFO = info
            _CACHE_REMOTE_TS = now
            return info
    except Exception:
        pass

    return {
        "status": "offline",
        "url": url,
        "version": "unknown",
        "active_operations": [],
        "total_operations": 0,
    }
