import uuid

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)


class QueryResult(BaseModel):
    instance_id: uuid.UUID
    columns: list[str]
    rows: list[list[str | None]]
    row_count: int
    truncated: bool
