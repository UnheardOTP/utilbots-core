"""Website factory. A bot's `app/web/app.py` is typically:

    from utilbots_core.web import create_app
    from .routes import router            # the bot's own pages (e.g. its /guild/{id} settings)
    app = create_app(routers=[router], templates_dir=Path(__file__).parent / "templates")
"""
import asyncio
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .. import billing, registry
from ..db import init_db
from .deps import LoginRequired, use_templates
from .routes import login_redirect, router as core_router

CORE_STATIC = Path(__file__).parent / "static"


def create_app(*, routers: Iterable[APIRouter] = (), templates_dir: Path | None = None,
               static_dir: Path | None = None, seed: Callable[[Session], None] | None = None,
               admin_stats: Callable[[Session], Iterable[tuple[str, object]]] | None = None,
               on_startup: Callable[[FastAPI], object] | None = None,
               on_shutdown: Callable[[FastAPI], object] | None = None, init_database: bool = True) -> FastAPI:
    spec = registry.spec()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if init_database:
            init_db(seed)
            asyncio.get_running_loop().run_in_executor(None, billing.ensure_stripe)
        if on_startup:
            res = on_startup(app)
            if asyncio.iscoroutine(res):
                await res
        yield
        if on_shutdown:
            res = on_shutdown(app)
            if asyncio.iscoroutine(res):
                await res

    app = FastAPI(title=spec.name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.admin_stats = admin_stats
    use_templates(templates_dir)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return login_redirect(request)

    app.mount("/core-static", StaticFiles(directory=CORE_STATIC), name="core-static")
    if static_dir and static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    for r in routers:  # bot routes first, so they override core pages with the same path
        app.include_router(r)
    app.include_router(core_router)
    return app
