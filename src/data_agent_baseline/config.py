from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _resolve_env(value: str) -> str:
    """Expand ${VAR} or ${VAR:-default} placeholders using process environment.

    Required by the KDD Cup 2026 submission rules: API key/URL must come from
    environment variables injected by the evaluation system rather than being
    hardcoded into the image.
    """

    def _sub(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2) or ""
        return os.environ.get(var_name, default_value)

    return _ENV_PATTERN.sub(_sub, value)


def _default_dataset_root() -> Path:
    return PROJECT_ROOT / "data" / "public" / "input"


def _default_run_output_dir() -> Path:
    return PROJECT_ROOT / "artifacts" / "runs"


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    root_path: Path = field(default_factory=_default_dataset_root)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    model: str = "gpt-4.1-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    max_steps: int = 16
    temperature: float = 0.0
    agent_type: str = "langgraph"  # "langgraph" or "react"


@dataclass(frozen=True, slots=True)
class RunConfig:
    output_dir: Path = field(default_factory=_default_run_output_dir)
    run_id: str | None = None
    max_workers: int = 4
    task_timeout_seconds: int = 600
    # 1 = legacy single-pass behavior. 2 or 3 = enable cross-round voting:
    # round 1 writes prediction.csv (baseline); rounds 2/3 write r2.csv /
    # r3.csv (or back-fill prediction.csv if round 1 produced nothing); a
    # final voting pass picks the majority answer and overwrites
    # prediction.csv. Capped at 3 deliberately: the voting rule (3 distinct
    # → fall back to round 1) is only designed for up to 3 candidates.
    vote_rounds: int = 1


@dataclass(frozen=True, slots=True)
class AppConfig:
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    run: RunConfig = field(default_factory=RunConfig)


def _path_value(raw_value: str | None, default_value: Path) -> Path:
    if not raw_value:
        return default_value
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()


def load_app_config(config_path: Path) -> AppConfig:
    payload = yaml.safe_load(config_path.read_text()) or {}
    dataset_defaults = DatasetConfig()
    agent_defaults = AgentConfig()
    run_defaults = RunConfig()

    dataset_payload = payload.get("dataset", {})
    agent_payload = payload.get("agent", {})
    run_payload = payload.get("run", {})

    dataset_config = DatasetConfig(
        root_path=_path_value(dataset_payload.get("root_path"), dataset_defaults.root_path),
    )
    raw_agent_type = str(agent_payload.get("agent_type", agent_defaults.agent_type)).strip().lower()
    if raw_agent_type not in ("langgraph", "react"):
        raise ValueError(
            f"agent.agent_type must be 'langgraph' or 'react', got '{raw_agent_type}'"
        )
    agent_config = AgentConfig(
        model=_resolve_env(str(agent_payload.get("model", agent_defaults.model))),
        api_base=_resolve_env(str(agent_payload.get("api_base", agent_defaults.api_base))),
        api_key=_resolve_env(str(agent_payload.get("api_key", agent_defaults.api_key))),
        max_steps=int(agent_payload.get("max_steps", agent_defaults.max_steps)),
        temperature=float(agent_payload.get("temperature", agent_defaults.temperature)),
        agent_type=raw_agent_type,
    )
    raw_run_id = run_payload.get("run_id")
    run_id = run_defaults.run_id
    if raw_run_id is not None:
        normalized_run_id = str(raw_run_id).strip()
        run_id = normalized_run_id or None

    vote_rounds = int(run_payload.get("vote_rounds", run_defaults.vote_rounds))
    if not 1 <= vote_rounds <= 3:
        raise ValueError(
            f"run.vote_rounds must be in [1, 3], got {vote_rounds}. "
            "The voting tiebreak rule is only designed for up to 3 rounds."
        )

    run_config = RunConfig(
        output_dir=_path_value(run_payload.get("output_dir"), run_defaults.output_dir),
        run_id=run_id,
        max_workers=int(run_payload.get("max_workers", run_defaults.max_workers)),
        task_timeout_seconds=int(run_payload.get("task_timeout_seconds", run_defaults.task_timeout_seconds)),
        vote_rounds=vote_rounds,
    )
    return AppConfig(dataset=dataset_config, agent=agent_config, run=run_config)
