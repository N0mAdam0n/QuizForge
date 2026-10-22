import logging
import ssl
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import models
from app.api import deps
from app.services.telemetry import telemetry

router = APIRouter()
logger = logging.getLogger(__name__)


class TelemetryConsentUpdate(BaseModel):
    consent: bool


class TelemetryPublicStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_devices: int = Field(ge=0, strict=True)
    active_devices_7d: int = Field(ge=0, strict=True)
    active_devices_30d: int = Field(ge=0, strict=True)
    total_events: int = Field(ge=0, strict=True)
    generated_at: datetime


@router.get("/stats/public", response_model=TelemetryPublicStats)
async def read_public_telemetry_stats(
    _current_user: models.User = Depends(deps.get_current_active_superuser),
) -> TelemetryPublicStats:
    try:
        data = await telemetry.fetch_public_stats()
        return TelemetryPublicStats.model_validate(data)
    except (
        httpx.HTTPError,
        ssl.SSLError,
        OSError,
        ValueError,
        ValidationError,
    ) as error:
        logger.debug(
            "Could not refresh public telemetry statistics (%s)",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="累计统计暂时不可用",
        ) from error


@router.get("/consent")
async def read_telemetry_consent(
    _current_user: models.User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    return {
        "enabled": telemetry.enabled,
        "consent": telemetry.consent_status(),
    }


@router.put("/consent")
async def update_telemetry_consent(
    payload: TelemetryConsentUpdate,
    _current_user: models.User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    consent = telemetry.set_consent(payload.consent)
    return {"enabled": telemetry.enabled, "consent": consent}
