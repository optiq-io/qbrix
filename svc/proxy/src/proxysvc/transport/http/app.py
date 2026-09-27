from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

from qbrixlog import get_logger

from proxysvc.transport.http.router.agent import router as agent_router
from proxysvc.transport.http.router.experiment import router as experiment_router
from proxysvc.transport.http.router.policy import router as policy_router
from proxysvc.transport.http.router.pool import router as pool_router
from proxysvc.transport.http.router.auth import router as auth_router
from proxysvc.transport.http.router.gate import router as gate_router
from proxysvc.transport.http.router.runtime import router as runtime_router
from proxysvc.transport.http.exception import BaseAPIException
from proxysvc.transport.http.exception.schema import ErrorResponse

from proxysvc.transport.http.auth.middleware import AuthMiddleware
from proxysvc.transport.http.cors import ScopedCORSMiddleware
from proxysvc.transport.http.cors import AGENT_CORS_POLICY
from proxysvc.transport.http.cors import AGENT_CORS_PREFIXES
from proxysvc.transport.http.cors import DEFAULT_CORS_POLICY
from proxysvc.transport.http.auth.seed import seed_dev_user
from proxysvc import edition
from proxysvc.config import settings

__all__ = ["app"]

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa
    logger.info("proxy http server initializing")

    if settings.runenv == "dev":
        # attention: happens only during http spin up, not for grpc.
        # let it crash the container loudly — with migrations run ahead of proxy
        # startup, a seed failure here is a real bug, not an empty-db race.
        await seed_dev_user()

    logger.info("proxy http server initialized")
    yield
    logger.info("proxy http server terminated")


# docs/redoc/openapi expose every route, so keep them dev-only
_expose_docs = settings.runenv == "dev"

app = FastAPI(
    title="Qbrix API ",
    version=version("proxysvc"),
    description="Variant Optimisation Platform",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "APIKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API Key authentication. Format: optiq_<key>",
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token authentication",
        },
    }

    _attach_error_responses(openapi_schema)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# standard error envelope responses attached to every documented operation so SDKs
# generate the real {code, detail, context} shape instead of only FastAPI's 422
_STANDARD_ERROR_RESPONSES: dict[str, str] = {
    "400": "bad request",
    "401": "unauthorized",
    "403": "forbidden",
    "404": "not found",
    "409": "conflict",
    "429": "rate limit exceeded",
    "500": "internal server error",
    "503": "service unavailable",
}


def _attach_error_responses(openapi_schema: dict) -> None:
    """register the ErrorResponse schema and reference it from standard 4xx/5xx
    responses on every documented operation."""
    schemas = openapi_schema["components"].setdefault("schemas", {})

    error_schema = ErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    # hoist nested defs (the ErrorCode enum) into components/schemas
    for name, definition in error_schema.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["ErrorResponse"] = error_schema

    error_content = {
        "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
    }

    for path_item in openapi_schema.get("paths", {}).values():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            for status_code, description in _STANDARD_ERROR_RESPONSES.items():
                responses.setdefault(
                    status_code,
                    {"description": description, "content": error_content},
                )


app.openapi = custom_openapi

# cors has to be outside auth, so auth goes first.
app.add_middleware(AuthMiddleware)

app.add_middleware(
    ScopedCORSMiddleware,
    scoped_prefixes=AGENT_CORS_PREFIXES,
    scoped_policy=AGENT_CORS_POLICY,
    default_policy=DEFAULT_CORS_POLICY,
)

app.include_router(auth_router, prefix="/api")
app.include_router(experiment_router, prefix="/api/v1")
app.include_router(pool_router, prefix="/api/v1")
app.include_router(policy_router, prefix="/api/v1")
app.include_router(gate_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(runtime_router, prefix="/api/v1")

if settings.analytics_enabled:
    from proxysvc.transport.http.router.analytics.event import router as event_router
    from proxysvc.transport.http.router.analytics.insight.experiment import (
        router as insight_router,
    )
    from proxysvc.transport.http.router.analytics.insight.tenant import (
        router as workspace_insight_router,
    )

    for analytics_router in (event_router, insight_router, workspace_insight_router):
        app.include_router(analytics_router, prefix="/api/v1")
    logger.info("analytics endpoints registered")

edition.register_routes(app, settings)


@app.exception_handler(BaseAPIException)
async def handle_api_exception(request: Request, exc: BaseAPIException):  # noqa
    log = logger.error if exc.status_code >= 500 else logger.info
    log(
        "api error: %s, status code: %s, path: %s",
        exc.detail,
        exc.status_code,
        request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
        headers=exc.headers or None,
    )


@app.get("/health", tags=["info"])
@app.get("/api/health", tags=["info"], include_in_schema=False)
async def health() -> dict:
    """health check endpoint."""
    return {"status": "healthy"}


@app.get("/info", tags=["info"])
async def info() -> dict:
    return {
        "name": "QbrixProxy",
        "description": "Qbrix HTTP Interface.",
        "version": app.version,
    }
