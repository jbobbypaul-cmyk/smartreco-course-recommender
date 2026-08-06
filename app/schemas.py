from datetime import datetime
from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    event_type: str = Field(pattern="^(page_view|product_view|search|product_click|dwell|add_to_cart)$")
    product_id: int | None = None
    query: str | None = Field(default=None, max_length=500)
    dwell_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    metadata: dict = Field(default_factory=dict)
    occurred_at: datetime


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=50)

