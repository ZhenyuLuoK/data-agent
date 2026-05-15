"""Expose default :class:`AgentOverrides` to the frontend.

Critical: never echo the raw API key. Only ``api_key_set`` is returned so
the UI can decide whether to require the user to type one.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from data_agent_baseline.web.schemas import DefaultsResponse
from data_agent_baseline.web.services.config_builder import load_base_app_config

router = APIRouter(tags=["config"])


@router.get("/config/defaults", response_model=DefaultsResponse)
async def get_defaults(request: Request) -> DefaultsResponse:
    settings = request.app.state.settings
    base = load_base_app_config(settings.base_config_path)
    return DefaultsResponse(
        model=base.agent.model,
        api_base=base.agent.api_base,
        # Same sentinel handling as runs.create_run: a YAML ``api_key:`` (null)
        # ends up as the literal string ``"None"`` after ``load_app_config``.
        api_key_set=bool(
            (base.agent.api_key or "").strip()
            and (base.agent.api_key or "").strip().lower() != "none"
        ),
        max_steps=base.agent.max_steps,
        temperature=base.agent.temperature,
        task_timeout_seconds=base.run.task_timeout_seconds,
        vote_rounds=base.run.vote_rounds,
        max_concurrent_runs=settings.max_concurrent_runs,
    )
