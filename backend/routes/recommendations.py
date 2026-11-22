from fastapi import APIRouter, HTTPException

from ..catalog import destinations, places
from ..schemas.recommendations import Recommendation, RecommendationRequest, RecommendationResponse

router = APIRouter()


@router.post("/recommendations")
def recommend(request: RecommendationRequest) -> RecommendationResponse:
    if request.tripworld_region_id not in {item.id for item in destinations}:
        raise HTTPException(status_code=422, detail="Unknown destination")
    visited = set(request.visited_place_ids)
    if visited.difference(item.id for item in places):
        raise HTTPException(status_code=422, detail="Unknown past place")
    candidates = [item for item in places
                  if item.tripworld_region_id == request.tripworld_region_id
                  and item.id not in visited
                  and (request.bounds is None or request.bounds.contains(item))]
    past_by_category = {place.category: place for place in places if place.id in visited}

    def explanation(place):
        past = past_by_category.get(place.category)
        if past and place.category:
            return f"You visited {past.name}. Both places are in the {place.category.lower()} category."
        return f"A different kind of stop to explore in {place.locality or 'this destination'}."

    return RecommendationResponse(results=[
        Recommendation(**item.model_dump(), rank=rank,
                       explanation=explanation(item))
        for rank, item in enumerate(candidates[:10], start=1)
    ])
