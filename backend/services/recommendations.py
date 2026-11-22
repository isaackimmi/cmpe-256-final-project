"""Shared recommendation boundary; currently backed by the sample catalog.

Keep candidate selection separate from the top-ten display cutoff so feedback can
use the full pool. Future model serving can replace this source without changing
HTTP contracts or the agent's dependence on trusted catalog records.
"""

from fastapi import HTTPException

from ..catalog import destinations, places
from ..models import Place
from ..schemas.recommendations import Recommendation, RecommendationRequest, RecommendationResponse


def get_candidates(request: RecommendationRequest) -> list[Place]:
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
    return build_recommendations(get_candidates(request)[:10], request.visited_place_ids)
