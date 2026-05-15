"""Merge user-supplied :class:`AgentOverrides` into a base :class:`AppConfig`.

The base ``AppConfig`` is loaded once from disk (env vars in the YAML
already expanded by :func:`load_app_config`). Each ``POST /api/runs`` then
calls :func:`build_run_config` to derive a request-scoped config without
mutating the shared base — important because ``AppConfig`` and its nested
dataclasses are ``frozen=True``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from data_agent_baseline.config import AppConfig, DatasetConfig, load_app_config
from data_agent_baseline.web.schemas import AgentOverrides


def load_base_app_config(base_config_path: Path) -> AppConfig:
    """Load the YAML default; missing file is fatal at startup, not silent."""
    if not base_config_path.exists():
        raise FileNotFoundError(
            f"DABENCH_WEB_BASE_CONFIG points to a missing file: {base_config_path}"
        )
    return load_app_config(base_config_path)


def build_run_config(
    *,
    base: AppConfig,
    dataset_root: Path,
    overrides: AgentOverrides,
) -> AppConfig:
    """Apply ``overrides`` (and the per-run ``dataset_root``) on top of ``base``.

    Only fields that the user actually set (non-None) override the base —
    this preserves the YAML defaults for anything the UI didn't touch.
    """
    # ----- agent ----------
    agent_changes: dict[str, object] = {}
    if overrides.model is not None:
        agent_changes["model"] = overrides.model
    if overrides.api_base is not None:
        agent_changes["api_base"] = overrides.api_base
    if overrides.api_key is not None:
        agent_changes["api_key"] = overrides.api_key
    if overrides.max_steps is not None:
        agent_changes["max_steps"] = overrides.max_steps
    if overrides.temperature is not None:
        agent_changes["temperature"] = overrides.temperature
    new_agent = replace(base.agent, **agent_changes) if agent_changes else base.agent

    # ----- run ----------
    run_changes: dict[str, object] = {}
    if overrides.task_timeout_seconds is not None:
        run_changes["task_timeout_seconds"] = overrides.task_timeout_seconds
    if overrides.vote_rounds is not None:
        run_changes["vote_rounds"] = overrides.vote_rounds
    new_run = replace(base.run, **run_changes) if run_changes else base.run

    # ----- dataset ----------
    new_dataset = DatasetConfig(root_path=dataset_root)

    return AppConfig(dataset=new_dataset, agent=new_agent, run=new_run)
