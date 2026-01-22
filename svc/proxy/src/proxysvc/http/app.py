import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from proxysvc.http.router.agent import router as agent_router
from proxysvc.http.router.experiment import router as experiment_router
from proxysvc.http.router.pool import router as pool_router
from proxysvc.http.router.auth import router as auth_router
from proxysvc.http.router.gate import router as gate_router
from proxysvc.http.exception import BaseAPIException

from proxysvc.http.auth.middleware import AuthMiddleware
from proxysvc.http.auth.seed import seed_dev_user
from proxysvc.config import settings

__all__ = ["app"]


def configure_logging(log_level=logging.INFO):
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(log_config)


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa
    logger.info("proxy http server initializing...")

    # seed dev user in dev mode
    if settings.runenv == "dev":
        try:
            await seed_dev_user()
        except Exception as e:
            logger.warning(f"failed to seed dev user: {e}")

    logger.info("proxy http server initialized")
    yield
    logger.info("proxy http server terminated")


app = FastAPI(
    title="qbrix API",
    version="0.1.0",
    description="Multi-Armed Bandit Optimization Platform",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
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
    )  # noqa

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

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(experiment_router, prefix="/api/v1")
app.include_router(pool_router, prefix="/api/v1")
app.include_router(gate_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")


@app.middleware("http")
async def logger_middleware(request: Request, call_next):
    logger.info("processing request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


@app.exception_handler(BaseAPIException)
async def handle_api_exception(request: Request, exc: BaseAPIException):
    logger.error(
        f"api error: {exc.detail}, status code: {exc.status_code}, path: {request.url.path}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.get("/health", tags=["info"])
async def health() -> dict:
    """health check endpoint."""
    return {"status": "healthy"}


@app.get("/info", tags=["info"])
async def info() -> dict:
    return {
        "name": "QbrixProxy",
        "description": "Qbrix HTTP Interface.",
        "version": "0.1.0",
    }
