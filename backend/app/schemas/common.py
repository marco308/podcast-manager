"""Response schemas shared across routers."""

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """A bare confirmation, e.g. from a delete or a logout."""

    message: str


class HealthResponse(BaseModel):
    """``GET /api/health``."""

    status: str
    app: str
    version: str
    # The image's git commit, "unknown" outside a built image.
    commit: str
