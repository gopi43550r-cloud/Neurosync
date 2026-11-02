"""NeuroSync FastAPI application entrypoint."""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import (
    agents,
    audit,
    blackboard,
    chat,
    claims,
    conflicts,
    credibility,
    demo,
    documents,
    evidence,
    graph,
    health,
    hypotheses,
    investigations,
    reviews,
    search,
    settings as settings_api,
    verification,
)
from .config import settings
from .database import init_db
from .logging_config import configure_logging

configure_logging(
    level=settings.log_level,
    json_format=settings.json_logs,
    secrets=settings.secret_values,
)
logger = logging.getLogger("neurosync")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(
        "NeuroSync started (mode=%s, environment=%s)",
        "ai" if settings.llm_configured else "demonstration",
        settings.environment,
    )
    yield


app = FastAPI(
    title="NeuroSync API",
    description=(
        "Evidence-driven multi-agent Blackboard Architecture for detecting and "
        "resolving conflicting information."
    ),
    version=__version__,
    lifespan=lifespan,
    # Interactive docs are a development convenience; disable them in
    # production via ENABLE_DOCS=false to reduce the exposed surface area.
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

if settings.trusted_host_list and "*" not in settings.trusted_host_list:
    # Defence-in-depth against Host-header attacks. Enabled only when explicit
    # hosts are configured; left off when TRUSTED_HOSTS is "*".
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)

def resolve_cors_credentials(origins: list[str]) -> bool:
    """Credentials are never combined with a wildcard origin (browser spec)."""
    return settings.cors_allow_credentials and "*" not in origins


cors_origins = settings.cors_origin_list
cors_allow_credentials = resolve_cors_credentials(cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Token", "").strip()


def _is_events_stream(request: Request) -> bool:
    return request.url.path.endswith("/events")


@app.middleware("http")
async def api_token_auth(request: Request, call_next):
    """Optional bearer-token guard for the API.

    Disabled by default (empty ``API_TOKEN``) for loopback-only deployments.
    When ``API_TOKEN`` is set, every ``/api/*`` route requires it. Browser
    ``EventSource`` cannot send headers, so the SSE stream additionally accepts
    the token as a ``?token=`` query parameter (a documented trade-off).
    """
    token = settings.api_token
    if not token:
        return await call_next(request)
    path = request.url.path
    # CORS preflights must never require credentials, and health probes are
    # exempt so load balancers and monitors can work without storing secrets.
    if request.method == "OPTIONS" or path.startswith("/api/health"):
        return await call_next(request)
    if path.startswith("/api/"):
        provided = _extract_bearer(request)
        if not provided and _is_events_stream(request):
            provided = request.query_params.get("token", "")
        if not provided or not hmac.compare_digest(provided, token):
            return JSONResponse(
                status_code=401, content={"detail": "Unauthorized.", "code": "unauthorized"}
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


# --------------------------------------------------------------- error handling
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail), "code": "http_error"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed.", "code": "validation_error", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    # Never leak stack traces or secrets to clients.
    return JSONResponse(status_code=500, content={"detail": "Internal server error.", "code": "internal_error"})


# --------------------------------------------------------------------- routes
API = "/api"
app.include_router(health.router, prefix=API)
app.include_router(documents.router, prefix=API)
app.include_router(claims.router, prefix=API)
app.include_router(conflicts.router, prefix=API)
app.include_router(evidence.router, prefix=API)
app.include_router(hypotheses.router, prefix=API)
app.include_router(investigations.router, prefix=API)
app.include_router(verification.router, prefix=API)
app.include_router(credibility.router, prefix=API)
app.include_router(chat.router, prefix=API)
app.include_router(blackboard.router, prefix=API)
app.include_router(graph.router, prefix=API)
app.include_router(agents.router, prefix=API)
app.include_router(search.router, prefix=API)
app.include_router(audit.router, prefix=API)
app.include_router(reviews.router, prefix=API)
app.include_router(settings_api.router, prefix=API)
app.include_router(demo.router, prefix=API)


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "api": API,
        "mode": "ai" if settings.llm_configured else "demonstration",
    }
