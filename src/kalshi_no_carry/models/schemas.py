"""Pydantic schemas for normalized entities (expand as persistence matures)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EventClusterRecord(BaseModel):
    """Planned normalized cluster row for storage layers."""

    model_config = ConfigDict(frozen=True)

    cluster_id: str = Field(..., min_length=1)
    reference_time_utc: datetime
    label: str | None = None
