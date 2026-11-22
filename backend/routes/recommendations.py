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
    return RecommendationResponse(results=[
        Recommendation(**item.model_dump(), rank=rank,
                       explanation="Demo result for this destination.")
        for rank, item in enumerate(candidates[:10], start=1)
    ])
