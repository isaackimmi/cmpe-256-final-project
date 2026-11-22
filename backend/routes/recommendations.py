from fastapi import APIRouter, HTTPException

from ..catalog import places
from ..destination_catalog import Catalog
from ..schemas.recommendations import Recommendation, RecommendationRequest, RecommendationResponse

router = APIRouter()


@router.post("/recommendations")
def recommend(request: RecommendationRequest) -> RecommendationResponse:
    with Catalog() as catalog:
        destination = catalog.get_destination(request.tripworld_region_id)
    if destination is None:
        raise HTTPException(status_code=422, detail="Unknown destination")
    visited = set(request.visited_place_ids)
    if visited.difference(item.id for item in places):
        raise HTTPException(status_code=422, detail="Unknown past place")
    if request.tripworld_region_id not in {item.tripworld_region_id for item in places}:
        raise HTTPException(status_code=503, detail="Recommendations are not available for this destination yet.")
    candidates = [item for item in places
                  if item.tripworld_region_id == request.tripworld_region_id
                  and item.id not in visited
                  and (request.bounds is None or request.bounds.contains(item))]
    past_by_category = {place.category: place for place in places if place.id in visited}

    def explanation(place):
        past = past_by_category.get(place.category)
        if past and place.category:
            return f"Sample result: you visited {past.name}. Both places are in the {place.category.lower()} category."
        return f"Sample result: a different kind of stop to explore in {place.locality or 'this destination'}."

    return RecommendationResponse(results=[
        Recommendation(**item.model_dump(), rank=rank,
                       explanation=explanation(item))
        for rank, item in enumerate(candidates[:10], start=1)
    ])
