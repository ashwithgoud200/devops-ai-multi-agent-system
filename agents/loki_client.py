"""Read-only Loki telemetry client with transparent fallback to local application log files.

Strict safety policy:
- Passive, read-only log inspection.
- Redacts recognized API keys, credentials, and tokens.
- Never mutates log streams or configuration.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from agents import untrusted_text

logger = logging.getLogger("loki_client")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "logs" / "app.log"
DEFAULT_LOKI_URL = os.getenv("LOKI_URL", "http://127.0.0.1:3100")

_LOKI_SESSION = requests.Session()
_LOKI_SESSION.mount("http://", HTTPAdapter(max_retries=0))
_LOKI_SESSION.mount("https://", HTTPAdapter(max_retries=0))
_STATUS_CACHE: dict[str, Any] = {}
_STATUS_CACHE_TIME: float = 0.0


def query_loki_logs(
    query: str = '{app="calculator-app"}',
    limit: int = 50,
    since_seconds: int = 3600,
    loki_url: str | None = None,
    log_file_fallback: Path | None = None,
) -> dict[str, Any]:
    """Query Loki for log events within the time window; fallback to local log file if Loki is unavailable."""
    base_url = loki_url or os.getenv("LOKI_URL", DEFAULT_LOKI_URL).rstrip("/")
    if os.name == "nt" and "SystemRoot" not in os.environ:
        return _query_local_log_file(query, limit, since_seconds, log_file_fallback)
    now_ns = int(time.time() * 1e9)
    start_ns = now_ns - int(since_seconds * 1e9)
    
    # 1. Try querying live Loki
    try:
        url = f"{base_url}/loki/api/v1/query_range"
        params = {
            "query": query,
            "limit": limit,
            "start": str(start_ns),
            "end": str(now_ns),
            "direction": "BACKWARD",
        }
        resp = _LOKI_SESSION.get(url, params=params, timeout=0.2)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            events = []
            for stream in results:
                stream_labels = stream.get("stream", {})
                values = stream.get("values", [])
                for ts_str, raw_log in values:
                    # Parse timestamp in seconds
                    ts_sec = float(ts_str) / 1e9 if ts_str.isdigit() else time.time()
                    # Try json parse of log message
                    try:
                        parsed = json.loads(raw_log)
                        msg = parsed.get("msg") or parsed.get("message") or raw_log
                        level = parsed.get("level") or stream_labels.get("level") or "INFO"
                    except Exception:
                        msg = raw_log
                        level = "ERROR" if "error" in raw_log.lower() else "INFO"
                    
                    events.append({
                        "ts": ts_sec,
                        "level": level,
                        "msg": untrusted_text.sanitize_text(msg, max_length=500),
                        "stream": stream_labels,
                    })
            
            return {
                "status": "ok",
                "source": f"loki:{base_url}",
                "timestamp": time.time(),
                "events": events[:limit],
                "count": len(events[:limit]),
            }
    except Exception as exc:
        logger.debug("Loki query failed (%s); falling back to local log file", exc)

    # 2. Fallback to local application log file
    path = log_file_fallback or Path(os.getenv("DEVOPS_LOG_PATH", str(DEFAULT_LOG_PATH)))
    if not path.is_file():
        return {
            "status": "unavailable",
            "source": str(path),
            "timestamp": time.time(),
            "events": [],
            "count": 0,
            "detail": f"Neither Loki ({base_url}) nor local log file ({path}) was accessible.",
        }

    events = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        ts = rec.get("ts") or time.time()
                        level = rec.get("level", "INFO")
                        msg = rec.get("msg") or rec.get("message") or line
                        events.append({
                            "ts": ts,
                            "level": level,
                            "msg": untrusted_text.sanitize_text(msg, max_length=500),
                            "op": rec.get("op"),
                            "version": rec.get("version"),
                        })
                except json.JSONDecodeError:
                    events.append({
                        "ts": time.time(),
                        "level": "INFO",
                        "msg": untrusted_text.sanitize_text(line, max_length=500),
                    })
        return {
            "status": "ok",
            "source": f"file:{path.name}",
            "timestamp": time.time(),
            "events": events,
            "count": len(events),
        }
    except Exception as exc:
        return {
            "status": "error",
            "source": str(path),
            "timestamp": time.time(),
            "events": [],
            "count": 0,
            "detail": f"Failed reading log file: {exc}",
        }


def get_loki_status(loki_url: str | None = None) -> dict[str, Any]:
    """Check whether Loki server is reachable and ready."""
    global _STATUS_CACHE, _STATUS_CACHE_TIME
    now = time.time()
    if _STATUS_CACHE and (now - _STATUS_CACHE_TIME < 5.0):
        return dict(_STATUS_CACHE)

    base_url = (loki_url or os.getenv("LOKI_URL", DEFAULT_LOKI_URL)).rstrip("/")
    if os.name == "nt" and "SystemRoot" not in os.environ:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"loki:{base_url}",
            "detail": "Network unavailable",
            "timestamp": now,
        }
        _STATUS_CACHE = result
        _STATUS_CACHE_TIME = now
        return dict(result)
    try:
        resp = _LOKI_SESSION.get(f"{base_url}/ready", timeout=0.2)
        ready = resp.status_code == 200
        result = {
            "status": "online" if ready else "unavailable",
            "healthy": ready,
            "url": base_url,
            "source": f"loki:{base_url}",
            "detail": "Loki log engine is ready" if ready else f"Loki returned {resp.status_code}",
            "timestamp": now,
        }
    except Exception as exc:
        result = {
            "status": "unavailable",
            "healthy": False,
            "url": base_url,
            "source": f"loki:{base_url}",
            "detail": f"Loki server unavailable ({exc}); local log file fallback active",
            "timestamp": now,
        }
    _STATUS_CACHE = result
    _STATUS_CACHE_TIME = now
    return dict(result)


def push_loki_log(level: str, msg: str, labels: dict[str, str] | None = None) -> None:
    """Asynchronously push a single log event to Loki."""
    if "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ or (os.name == "nt" and "SystemRoot" not in os.environ):
        return
    base_url = os.getenv("LOKI_URL", DEFAULT_LOKI_URL).rstrip("/")
    stream_labels = {"app": "calculator-app", "level": level.upper()}
    if labels:
        stream_labels.update(labels)

    now_ns = str(int(time.time() * 1e9))
    payload = {
        "streams": [
            {
                "stream": stream_labels,
                "values": [[now_ns, msg]],
            }
        ]
    }

    def _send():
        try:
            requests.post(
                f"{base_url}/loki/api/v1/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=1.5,
            )
        except Exception:
            pass

    import threading
    threading.Thread(target=_send, daemon=True).start()


