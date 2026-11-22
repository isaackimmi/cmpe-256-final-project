from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


Item = TypeVar("Item")


class SearchPage(BaseModel, Generic[Item]):
    items: list[Item]
    next_offset: int | None
