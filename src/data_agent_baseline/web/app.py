"""FastAPI application factory + ``dabench-web`` console-script entry point.

Layout intent:
* Build the app inside :func:`create_app` so tests can construct an
  isolated instance with a custom :class:`WebSettings` (e.g. tmp_path
  dataset roots) instead of going through env vars.
* Mount static docs at ``/static/docs`` so ``docs/agent_architecture_summary.html``
  and ``docs/data-agent/html/index.html`` are reachable from the browser
  without any extra plumbing.
* Keep this module import-light: heavy submodules (FastAPI, watchfiles)
  are only imported here, never inside the rest of the package, so the
  CLI keeps working when ``[web]`` extras are not installed.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from data_agent_baseline.logging_setup import init_global_logging
from data_agent_baseline.web.api import config as config_router
from data_agent_baseline.web.api import health as health_router
from data_agent_baseline.web.api import runs as runs_router
from data_agent_baseline.web.api import stream as stream_router
from data_agent_baseline.web.api import tasks as tasks_router
from data_agent_baseline.web.api import uploads as uploads_router
from data_agent_baseline.web.security import install_api_key_redaction
from data_agent_baseline.web.services.run_manager import RunManager
from data_agent_baseline.web.settings import WebSettings

logger = logging.getLogger("data_agent_baseline.web")


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """Build a fresh FastAPI app bound to ``settings`` (defaults from env)."""
    init_global_logging()
    install_api_key_redaction()

    resolved_settings = settings or WebSettings.from_env()

    # The run manager is the single source of truth for active/recent runs.
    # Stored on ``app.state`` so routes can grab it via dependency injection
    # without module-level globals (which would break in-process tests).
    run_manager = RunManager(settings=resolved_settings)

    app = FastAPI(
        title="data-agent baseline web",
        version="0.1.0",
        description=(
            "HTTP/WebSocket facade over the data-agent-baseline LangGraph "
            "agent. See docs/backend_requirements.md for the contract."
        ),
    )
    app.state.settings = resolved_settings
    app.state.run_manager = run_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers — order doesn't matter, FastAPI dispatches by path.
    app.include_router(health_router.router, prefix="/api")
    app.include_router(config_router.router, prefix="/api")
    app.include_router(tasks_router.router, prefix="/api")
    app.include_router(uploads_router.router, prefix="/api")
    app.include_router(runs_router.router, prefix="/api")
    # WebSocket router uses the same ``/api`` prefix so the URL is
    # ``ws://host/api/runs/{run_id}/stream`` per backend spec §6.1.
    app.include_router(stream_router.router, prefix="/api")

    # Static docs mount: ``html=True`` lets ``…/index.html`` be served when
    # the user navigates to a directory URL (matches the second target
    # ``docs/data-agent/html/index.html``).
    if resolved_settings.docs_root.is_dir():
        app.mount(
            "/static/docs",
            StaticFiles(directory=resolved_settings.docs_root, html=True),
            name="docs",
        )
    else:
        logger.warning(
            "docs_root not found, /static/docs will return 404: %s",
            resolved_settings.docs_root,
        )

    # ---- 前端 SPA ----------------------------------------------------------
    # Docker 镜像构建时会把 web/dist 拷到 /app/web/dist，由后端直接托管，
    # 浏览器访问 http://host:8000 即可拿到 index.html，所有非 /api 非 /static
    # 路径都 fallback 到 index.html，让 react-router 接管路由。
    # 本地开发时若 dist 不存在，则跳过挂载，不影响前端独立 vite dev server。
    _mount_spa(app, resolved_settings.web_dist_root)

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:  # pragma: no cover — exercised by uvicorn
        await run_manager.shutdown()

    return app


def _mount_spa(app: FastAPI, dist_root) -> None:
    """Mount the built SPA at ``/`` with proper SPA fallback.

    Why not a single ``StaticFiles(html=True)`` at ``/``? Because that would
    shadow the ``/api`` and ``/static`` routes if mounted first, and 404 on
    deep links like ``/runs/abc`` if mounted last. We instead:
      1. Mount ``/assets`` (Vite hashed bundles) as plain static.
      2. Serve top-level static files (``favicon.svg``, ``index.html``).
      3. Add a catch-all GET that returns ``index.html`` for any unknown
         path that is *not* under ``/api`` or ``/static`` — this is the SPA
         fallback that lets ``react-router`` handle client-side routing.
    """
    if not dist_root.is_dir():
        logger.warning(
            "web_dist_root not found, SPA will not be served: %s "
            "(run `pnpm build` in ./web to generate it, "
            "or rely on the Vite dev server in development)",
            dist_root,
        )
        return

    index_html = dist_root / "index.html"
    if not index_html.is_file():
        logger.warning("web_dist_root missing index.html, skipping SPA mount: %s", dist_root)
        return

    assets_dir = dist_root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="spa-assets")

    @app.get("/", include_in_schema=False)
    async def _spa_index() -> FileResponse:
        return FileResponse(index_html, media_type="text/html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str, request: Request) -> FileResponse:
        # 反例保护：/api 与 /static 已由前面的路由/挂载点处理；如果走到这里
        # 说明确实是 404，应当返回标准 404 而不是把 index.html 灌回去——
        # 否则前端拿到 200 + html 会以为接口成功。
        if full_path.startswith(("api/", "static/")):
            raise HTTPException(status_code=404, detail="Not Found")

        # 顶层静态文件（如 favicon.svg）直接命中
        candidate = dist_root / full_path
        if candidate.is_file():
            return FileResponse(candidate)

        # 其他一切都交给 SPA：返回 index.html，react-router 处理路由
        return FileResponse(index_html, media_type="text/html")

    logger.info("SPA mounted from %s", dist_root)


# Default app instance for ``uvicorn data_agent_baseline.web.app:app``.
app = create_app()


def main() -> None:
    """Console-script entry point: ``dabench-web``.

    Honours ``DABENCH_WEB_HOST`` / ``DABENCH_WEB_PORT`` so operators can
    redeploy without editing code. ``--workers 1`` is hard-coded by spec
    (in-memory run registry — see backend doc §8.2).
    """
    import uvicorn  # local import: only required at run time, not import time

    settings = WebSettings.from_env()
    reload_flag = os.environ.get("DABENCH_WEB_RELOAD", "").lower() in {"1", "true", "yes"}
    uvicorn.run(
        "data_agent_baseline.web.app:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        reload=reload_flag,
        log_level=os.environ.get("DABENCH_WEB_LOG_LEVEL", "info").lower(),
        ws_max_size=16 * 1024 * 1024,  # 16 MiB — matches spec §6.4 long-line guarantee
    )


if __name__ == "__main__":  # pragma: no cover
    main()
