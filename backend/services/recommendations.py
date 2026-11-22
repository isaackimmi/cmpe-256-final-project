"""With the real model, this module should expose only recommend()."""

from fastapi import HTTPException

from ..catalog import destinations, places
from ..models import Place
from ..schemas.recommendations import Recommendation, RecommendationRequest, RecommendationResponse


def get_candidates(request: RecommendationRequest) -> list[Place]:
    # Temporary stub: select places from the sample catalog.
    if request.tripworld_region_id not in {item.id for item in destinations}:
        raise HTTPException(status_code=422, detail="Unknown destination")
    visited = set(request.visited_place_ids)
    if visited.difference(item.id for item in places):
        raise HTTPException(status_code=422, detail="Unknown past place")
    return [item for item in places
            if item.tripworld_region_id == request.tripworld_region_id
            and item.id not in visited
            and (request.bounds is None or request.bounds.contains(item))]


def build_recommendations(candidates: list[Place], visited_place_ids: list[str]) -> RecommendationResponse:
    # Temporary stub: format sample places and their canned explanations.
    visited = set(visited_place_ids)
    past_by_category = {place.category: place for place in places if place.id in visited}

    def explanation(place: Place) -> str:
        past = past_by_category.get(place.category)
        if past and place.category:
            return f"You visited {past.name}. Both places are in the {place.category.lower()} category."
        return f"A different kind of stop to explore in {place.locality or 'this destination'}."

    return RecommendationResponse(results=[
        Recommendation(**item.model_dump(), rank=rank, explanation=explanation(item))
        for rank, item in enumerate(candidates, start=1)
    ])


def recommend(request: RecommendationRequest) -> RecommendationResponse:
    # TODO(model-serving): Call the real model here. Move the feedback caller to
    # recommend() and delete both stub helpers.
    return build_recommendations(get_candidates(request)[:10], request.visited_place_ids)
