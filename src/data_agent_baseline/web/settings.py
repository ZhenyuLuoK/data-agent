"""Runtime configuration for the web server, sourced from environment variables.

Centralising env var reads here keeps the rest of the package free of
``os.environ`` lookups, which simplifies testing (tests can construct a
``WebSettings`` directly with overrides instead of monkey-patching env vars).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root resolves to the repository checkout: this file lives at
# ``src/data_agent_baseline/web/settings.py`` so we walk three parents up
# to land on the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _env_path(name: str, default: Path) -> Path:
    """Read an env var as a Path, resolving relative paths against the repo root."""
    raw = os.environ.get(name)
    if not raw:
        return default
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Resolved runtime configuration for the FastAPI server."""

    host: str = "0.0.0.0"
    port: int = 8000

    # Default ``AppConfig`` source — env-substituted ``api_key``/``api_base``
    # are honoured because the loader calls ``_resolve_env`` on each value.
    base_config_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "configs" / "react_baseline.local.yaml"
    )
    dataset_root: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "public" / "input")
    run_root: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts" / "runs")
    upload_root: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts" / "uploads")
    docs_root: Path = field(default_factory=lambda: PROJECT_ROOT / "docs")
    # 前端构建产物目录。Docker 镜像会把 web/dist 复制到 /app/web/dist；
    # 本地开发时仍可独立跑 vite dev server，不依赖此目录。
    web_dist_root: Path = field(default_factory=lambda: PROJECT_ROOT / "web" / "dist")

    # How many ``run_single_task`` invocations may execute concurrently. The
    # FastAPI process is intentionally single-worker (in-memory run registry),
    # so this is a process-local thread-pool size — independent of
    # ``run.max_workers`` in the base YAML config.
    max_concurrent_runs: int = 2

    # Upload guardrails (matches docs §5.3).
    max_upload_file_bytes: int = 200 * 1024 * 1024  # 200 MiB
    max_upload_total_bytes: int = 1024 * 1024 * 1024  # 1 GiB
    upload_extension_whitelist: tuple[str, ...] = (
        "csv", "tsv", "json", "jsonl", "xlsx", "xls",
        "parquet", "db", "sqlite", "sqlite3", "txt", "md",
    )

    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> "WebSettings":
        return cls(
            host=os.environ.get("DABENCH_WEB_HOST", "0.0.0.0"),
            port=_env_int("DABENCH_WEB_PORT", 8000),
            base_config_path=_env_path(
                "DABENCH_WEB_BASE_CONFIG",
                PROJECT_ROOT / "configs" / "react_baseline.local.yaml",
            ),
            dataset_root=_env_path(
                "DABENCH_WEB_DATASET_ROOT", PROJECT_ROOT / "data" / "public" / "input"
            ),
            run_root=_env_path("DABENCH_WEB_RUN_ROOT", PROJECT_ROOT / "artifacts" / "runs"),
            upload_root=_env_path(
                "DABENCH_WEB_UPLOAD_ROOT", PROJECT_ROOT / "artifacts" / "uploads"
            ),
            docs_root=_env_path("DABENCH_WEB_DOCS_ROOT", PROJECT_ROOT / "docs"),
            web_dist_root=_env_path("DABENCH_WEB_DIST_ROOT", PROJECT_ROOT / "web" / "dist"),
            max_concurrent_runs=_env_int("DABENCH_WEB_MAX_CONCURRENT_RUNS", 2),
            cors_origins=_env_csv("DABENCH_WEB_CORS_ORIGINS", ["*"]),
        )
