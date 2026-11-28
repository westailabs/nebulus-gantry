"""Public, read-only runtime UI config (GET /api/config).

Lets the frontend pick up instance profile switches such as the CPA demo mode at
load time, from instance env, without rebuilding the frontend. Returns no secrets
and needs no authentication.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


class UIConfigResponse(BaseModel):
    """Runtime UI switches. ``demo_firm_name`` is "" when unset."""

    demo_mode: bool
    demo_firm_name: str = ""


@router.get("", response_model=UIConfigResponse)
def get_ui_config() -> UIConfigResponse:
    return UIConfigResponse(demo_mode=settings.demo_mode, demo_firm_name=settings.demo_firm_name)
