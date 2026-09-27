import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from esp import __version__
from esp.config import get_settings
from esp.db import get_session
from esp.logging import configure_logging

configure_logging(get_settings().log_level)
log = logging.getLogger("esp.api")

app = FastAPI(
    title="Environmental Screening Platform API",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]
    postgis_version: str | None = None
    schema_revision: str | None = None


@app.get("/api/health", response_model=Health)
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> Health:
    try:
        postgis: str = session.execute(text("SELECT postgis_lib_version()")).scalar_one()
        revision: str | None = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    except SQLAlchemyError:
        log.exception("health check database query failed")
        response.status_code = 503
        return Health(status="degraded", version=__version__, database="unavailable")
    return Health(
        status="ok",
        version=__version__,
        database="ok",
        postgis_version=postgis,
        schema_revision=revision,
    )
