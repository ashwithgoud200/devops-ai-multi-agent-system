"""Defensive utilities for handling untrusted text from external scanners and CI."""
from __future__ import annotations

import re
from typing import Any

# Maximum lengths for structured fields
MAX_TITLE_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 2000
MAX_LOCATION_LENGTH = 500
MAX_IDENTIFIER_LENGTH = 100
MAX_PACKAGE_LENGTH = 200
MAX_VERSION_LENGTH = 100
MAX_REMEDIATION_LENGTH = 1000

# ANSI escape sequence regex
ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Non-printable control characters (exclude \t \n \r)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Unicode bidirectional control characters used for spoofing
BIDI_CHAR_PATTERN = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# Secret patterns to redact
SECRET_PATTERNS = [
    # Private keys
    (re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # GitHub tokens
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z]{10,48}\b"), "[REDACTED_SLACK_TOKEN]"),
    # AWS access key ID
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # Bearer tokens
    (re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.+=]{16,}\b", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    # JWT tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    # Generic password/api-key assignments
    (re.compile(r"(?i)\b(password|passwd|secret|api_key|apikey|access_token|auth_token)\s*([:=])\s*['\"]?([^\s'\";,]{6,})['\"]?"), r"\1\2[REDACTED_SECRET]"),
]

# Prompt injection patterns
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\bsystem\s+prompt\s*:"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an)\b"),
    re.compile(r"(?i)\b(?:human|assistant|user|system)\s*:\s*\w+"),
    re.compile(r"(?i)\b(?:new\s+instructions|override\s+instructions)\b"),
]


def strip_control_characters(text: str) -> str:
    """Remove ANSI escape sequences, control characters, and bidi overrides."""
    if not isinstance(text, str):
        return ""
    cleaned = ANSI_ESCAPE_PATTERN.sub("", text)
    cleaned = CONTROL_CHAR_PATTERN.sub("", cleaned)
    cleaned = BIDI_CHAR_PATTERN.sub("", cleaned)
    return cleaned


def redact_secrets(text: str) -> str:
    """Redact recognizable API tokens, private keys, passwords and secrets."""
    if not isinstance(text, str):
        return ""
    redacted = text
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def defuse_prompt_injection(text: str) -> str:
    """Neutralize prompt injection attempts by neutralizing instruction-like phrases."""
    if not isinstance(text, str):
        return ""
    defused = text
    for pattern in PROMPT_INJECTION_PATTERNS:
        defused = pattern.sub(lambda m: f"[defused: {m.group(0)}]", defused)
    return defused


def sanitize_text(
    text: Any,
    max_length: int = MAX_DESCRIPTION_LENGTH,
    *,
    redact: bool = True,
    defuse: bool = True,
) -> str:
    """Comprehensive sanitization for untrusted scanner text."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    cleaned = strip_control_characters(text)
    if redact:
        cleaned = redact_secrets(cleaned)
    if defuse:
        cleaned = defuse_prompt_injection(cleaned)

    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "... [truncated]"

    return cleaned


def sanitize_identifier(identifier: Any, max_length: int = MAX_IDENTIFIER_LENGTH) -> str:
    """Sanitize vulnerability and rule identifiers."""
    return sanitize_text(identifier, max_length=max_length, redact=False, defuse=True).strip()


def sanitize_location(location: Any, max_length: int = MAX_LOCATION_LENGTH) -> str:
    """Sanitize file paths, lines, and targets."""
    return sanitize_text(location, max_length=max_length, redact=True, defuse=True).strip()
