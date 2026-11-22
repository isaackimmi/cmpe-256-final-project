from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from ..models import Place


class Bounds(BaseModel):
    west: float = Field(ge=-180, le=180)
    east: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def validate_latitudes(self):
        if self.south > self.north:
            raise ValueError("south must be at or below north")
        return self

    def contains(self, place: Place) -> bool:
        in_range = self.west <= place.lng <= self.east
        if self.west > self.east:
            in_range = place.lng >= self.west or place.lng <= self.east
        return in_range and self.south <= place.lat <= self.north


class RecommendationRequest(BaseModel):
    tripworld_region_id: str = Field(
        validation_alias=AliasChoices("tripworld_region_id", "destination_region_id"),
        description="Use the id returned by /destinations/search.",
    )
    visited_place_ids: list[str] = Field(min_length=1)
    bounds: Bounds | None = None


class Recommendation(Place):
    rank: int
    explanation: str


class RecommendationResponse(BaseModel):
    # TODO(model-serving): Accept the loaded ranker artifact's version and pass it
    # through both responses when a real scoring adapter replaces the fixture.
    model_version: Literal["stub-v1"] = "stub-v1"
    results: list[Recommendation]
