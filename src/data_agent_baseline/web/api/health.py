"""Health endpoint — used by uptime probes and the frontend boot screen."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

router = APIRouter(tags=["meta"])


def _resolve_version() -> str:
    try:
        return version("data-agent-baseline")
    except PackageNotFoundError:  # pragma: no cover — editable install w/o metadata
        return "0.0.0"


@router.get("/health")
async def get_health() -> dict[str, object]:
    return {"ok": True, "version": _resolve_version()}
