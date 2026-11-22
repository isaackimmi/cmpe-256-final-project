from typing import Literal

from pydantic import BaseModel, Field
from .recommendations import RecommendationRequest, RecommendationResponse


class Vote(BaseModel):
    place_id: str
    vote: Literal["like", "dislike"]


class FeedbackRequest(RecommendationRequest):
    current_place_ids: list[str] = Field(max_length=10)
    feedback: list[Vote] = Field(max_length=100)


class FeedbackResponse(RecommendationResponse):
    added_place_ids: list[str]
    removed_place_ids: list[str]
    update_summary: str
