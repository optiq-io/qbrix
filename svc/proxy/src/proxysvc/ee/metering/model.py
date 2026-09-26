from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UsageContext(BaseModel):
    """resolved per-tenant billing context for the current period.

    holds everything the meter needs except the live count itself, which is
    always read fresh from redis. safe to cache for a short ttl.
    """

    tenant_id: str
    tier: str
    included: int  # included selections per period; -1 = custom/unlimited
    period_key: str
    period_start: datetime
    period_end: datetime
