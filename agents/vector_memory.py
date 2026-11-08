"""Vector Database and Semantic Search Memory for SRE Runbooks and Past Incidents (Box 5).

Provides episodic memory and vector similarity search without requiring external cloud databases.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VECTOR_STORE_DIR = ROOT / "data" / "vector_store"
DEFAULT_RUNBOOKS_DIR = ROOT / "data" / "runbooks"
DEFAULT_AUDIT_LOG_PATH = ROOT / "logs" / "incident_audit.jsonl"

_MEMORY_LOCK = threading.RLock()


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words and character n-grams for subword similarity."""
    cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
    words = [w for w in cleaned.split() if len(w) > 1]
    tokens = list(words)
    # Add 3-grams for robust matching of technical terms (e.g. 'calc', 'div', 'http')
    for w in words:
        if len(w) >= 4:
            for i in range(len(w) - 2):
                tokens.append(w[i : i + 3])
    return tokens


def _compute_vector(tokens: list[str]) -> dict[str, float]:
    """Compute normalized term-frequency vector with sublinear scaling."""
    counts = Counter(tokens)
    if not counts:
        return {}
    vec = {}
    for term, cnt in counts.items():
        vec[term] = 1.0 + math.log(cnt)
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm > 0:
        for term in vec:
            vec[term] /= norm
    return vec


def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute cosine similarity between two normalized sparse vectors."""
    if not vec1 or not vec2:
        return 0.0
    # Iterate over smaller dictionary for speed
    small, big = (vec1, vec2) if len(vec1) < len(vec2) else (vec2, vec1)
    dot = sum(val * big.get(term, 0.0) for term, val in small.items())
    return max(0.0, min(1.0, float(dot)))


class VectorMemoryStore:
    """Embedded local Vector Database for SRE Runbooks and Past Incident Episodes."""

    _instance: VectorMemoryStore | None = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> VectorMemoryStore:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.lock = threading.RLock()
        self.documents: list[dict[str, Any]] = []
        self.indexed_at: float = 0.0
        self._init_store()
        self._initialized = True

    def _init_store(self) -> None:
        with self.lock:
            self.load_or_rebuild()

    def load_or_rebuild(self) -> None:
        """Load persisted index if available, otherwise index runbooks and episodic memory."""
        with self.lock:
            store_file = DEFAULT_VECTOR_STORE_DIR / "documents.json"
            if store_file.exists():
                try:
                    data = json.loads(store_file.read_text(encoding="utf-8"))
                    self.documents = data.get("documents", [])
                    self.indexed_at = data.get("indexed_at", time.time())
                    if self.documents:
                        return
                except Exception:
                    pass
            self.rebuild_index()

    def rebuild_index(self) -> None:
        """Re-index all SRE Runbooks and past incident episodes from logs/incident_audit.jsonl."""
        with self.lock:
            new_docs: list[dict[str, Any]] = []

            # 1. Index SRE Runbooks
            runbooks = self._read_runbooks()
            for rb in runbooks:
                doc = {
                    "id": rb["id"],
                    "type": "runbook",
                    "title": rb["title"],
                    "category": rb["category"],
                    "severity": rb["severity"],
                    "service": rb["target_service"],
                    "summary": rb["summary"],
                    "content": rb["content"],
                    "vector": _compute_vector(_tokenize(rb["content"] + " " + rb["title"] + " " + rb["category"])),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                new_docs.append(doc)

            # 2. Index Episodic Memory (Past Incidents)
            episodes = self._read_past_incidents()
            for ep in episodes:
                content_str = (
                    f"Incident {ep['incident_id']} Scenario: {ep.get('scenario')} "
                    f"Root cause: {ep.get('root_cause')} Action: {ep.get('action')} "
                    f"Decision: {ep.get('decision')} Outcome: {ep.get('outcome')}"
                )
                doc = {
                    "id": f"incident-{ep['incident_id'][:8]}",
                    "type": "incident_episode",
                    "title": f"Past Incident: {ep.get('scenario', 'General Incident')}",
                    "category": "episodic_memory",
                    "severity": "medium",
                    "service": "calculator-app",
                    "summary": f"Resolved incident: {ep.get('action', 'investigate')} with outcome {ep.get('outcome')}.",
                    "content": content_str,
                    "metadata": ep,
                    "vector": _compute_vector(_tokenize(content_str)),
                    "created_at": ep.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                }
                new_docs.append(doc)

            self.documents = new_docs
            self.indexed_at = time.time()
            self._save_to_disk()

    def _save_to_disk(self) -> None:
        try:
            DEFAULT_VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
            store_file = DEFAULT_VECTOR_STORE_DIR / "documents.json"
            data = {
                "indexed_at": self.indexed_at,
                "count": len(self.documents),
                "documents": self.documents,
            }
            with store_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _read_runbooks(self) -> list[dict[str, Any]]:
        runbooks = []
        if not DEFAULT_RUNBOOKS_DIR.exists():
            return runbooks

        for path in sorted(DEFAULT_RUNBOOKS_DIR.glob("*.md")):
            try:
                raw = path.read_text(encoding="utf-8")
                rb_id = path.stem.split("-")[0].upper()
                title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else path.stem

                sev_match = re.search(r"-\s+\*\*Severity:\*\*\s*(.+)$", raw, re.MULTILINE)
                severity = sev_match.group(1).strip().lower() if sev_match else "medium"

                cat_match = re.search(r"-\s+\*\*Category:\*\*\s*(.+)$", raw, re.MULTILINE)
                category = cat_match.group(1).strip() if cat_match else "SRE Playbook"

                target_match = re.search(r"-\s+\*\*Target Service:\*\*\s*`?([^`\n]+)`?", raw, re.MULTILINE)
                target_service = target_match.group(1).strip() if target_match else "calculator-app"

                symptoms_match = re.search(r"## Symptoms\n([\s\S]*?)(?=##|\Z)", raw)
                symptoms = symptoms_match.group(1).strip() if symptoms_match else ""

                summary = symptoms.split("\n")[0].lstrip("- ").strip() if symptoms else title

                runbooks.append({
                    "id": rb_id,
                    "title": title,
                    "severity": severity,
                    "category": category,
                    "target_service": target_service,
                    "summary": summary,
                    "content": raw,
                    "filename": path.name,
                })
            except Exception:
                pass
        return runbooks

    def _read_past_incidents(self) -> list[dict[str, Any]]:
        if not DEFAULT_AUDIT_LOG_PATH.exists():
            return []

        incidents_by_id: dict[str, dict[str, Any]] = {}
        try:
            with DEFAULT_AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    inc_id = rec.get("incident_id")
                    if not inc_id:
                        continue
                    event = rec.get("event")
                    if inc_id not in incidents_by_id:
                        incidents_by_id[inc_id] = {
                            "incident_id": inc_id,
                            "timestamp": rec.get("timestamp"),
                            "events": [],
                            "action": "unknown",
                            "decision": "unknown",
                            "outcome": "unknown",
                        }
                    inc = incidents_by_id[inc_id]
                    inc["events"].append(event)
                    if event == "diagnosis_finished":
                        inc["remediation_action"] = rec.get("remediation_action")
                    elif event == "approval_decision":
                        inc["decision"] = rec.get("decision")
                        inc["action"] = rec.get("action")
                    elif event == "action_finished":
                        inc["outcome"] = rec.get("outcome_status")
        except Exception:
            return []

        # Return incidents that reached a decision or resolution
        resolved = [
            inc for inc in incidents_by_id.values()
            if inc["decision"] != "unknown" or inc["outcome"] != "unknown" or "diagnosis_finished" in inc["events"]
        ]
        return resolved

    def search(
        self,
        query: str,
        top_k: int = 3,
        doc_type: str | None = None,
        min_score: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Semantic similarity search against SRE runbooks and episodic memory."""
        with self.lock:
            q_tokens = _tokenize(query)
            q_vec = _compute_vector(q_tokens)
            if not q_vec:
                return []

            results = []
            for doc in self.documents:
                if doc_type and doc.get("type") != doc_type:
                    continue
                score = _cosine_similarity(q_vec, doc.get("vector", {}))
                if score >= min_score:
                    results.append({
                        "id": doc["id"],
                        "type": doc["type"],
                        "title": doc["title"],
                        "category": doc["category"],
                        "severity": doc["severity"],
                        "service": doc["service"],
                        "summary": doc["summary"],
                        "similarity_score": round(score, 4),
                        "content_snippet": doc["content"][:320] + "..." if len(doc["content"]) > 320 else doc["content"],
                        "full_content": doc["content"],
                    })

            results.sort(key=lambda x: x["similarity_score"], reverse=True)
            return results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        """Return memory store statistics."""
        with self.lock:
            runbooks_count = sum(1 for d in self.documents if d.get("type") == "runbook")
            incidents_count = sum(1 for d in self.documents if d.get("type") == "incident_episode")
            return {
                "total_documents": len(self.documents),
                "runbooks_indexed": runbooks_count,
                "past_incidents_indexed": incidents_count,
                "indexed_at": self.indexed_at,
                "store_path": str(DEFAULT_VECTOR_STORE_DIR / "documents.json"),
            }

    def list_runbooks(self) -> list[dict[str, Any]]:
        """List all indexed SRE runbooks."""
        with self.lock:
            return [
                {
                    "id": d["id"],
                    "title": d["title"],
                    "category": d["category"],
                    "severity": d["severity"],
                    "service": d["service"],
                    "summary": d["summary"],
                }
                for d in self.documents
                if d.get("type") == "runbook"
            ]


_STORE = VectorMemoryStore()


def get_vector_memory() -> VectorMemoryStore:
    return _STORE

