"""Security utilities: api_key fingerprinting + log filter.

The web layer never persists raw API keys (see backend requirements §9).
Instead we keep an 8-char SHA-256 fingerprint in ``run_meta.json`` so
operators can correlate runs to keys without leaking the secret.
"""

from __future__ import annotations

import hashlib
import logging
import re

# Loose matcher for OpenAI/DashScope-style keys. Tightening this would risk
# under-matching (and leaking a key); over-matching is harmless because the
# replacement is opaque.
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


def fingerprint_api_key(api_key: str | None) -> str | None:
    """Return a short, non-reversible fingerprint of an API key.

    ``None`` and empty strings yield ``None`` so callers can store the field
    as-is without conditional logic.
    """
    if not api_key:
        return None
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:8]


class ApiKeyRedactingFilter(logging.Filter):
    """Logging filter that masks ``sk-...`` substrings in any record message.

    Installed on the project logger so that even third-party libraries
    (langchain/openai) cannot accidentally leak keys via stack traces.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 — stdlib API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never crash logging
            return True
        if "sk-" not in message:
            return True
        redacted = _API_KEY_PATTERN.sub("sk-***REDACTED***", message)
        # ``record.msg`` is the format string; replacing it loses arg
        # interpolation, so we also clear args to avoid double-formatting.
        record.msg = redacted
        record.args = ()
        return True


def install_api_key_redaction() -> None:
    """Attach :class:`ApiKeyRedactingFilter` to the project + root loggers.

    Idempotent: re-attaching the same filter instance is a no-op for stdlib
    handlers, but we still guard with a sentinel attribute to keep handler
    filter lists short across reloads.
    """
    sentinel_attr = "_dabench_api_key_filter_attached"
    for logger_name in ("data_agent_baseline", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        if getattr(logger, sentinel_attr, False):
            continue
        logger.addFilter(ApiKeyRedactingFilter())
        setattr(logger, sentinel_attr, True)
