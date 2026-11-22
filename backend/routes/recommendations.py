from fastapi import APIRouter

from ..schemas.recommendations import RecommendationRequest, RecommendationResponse
from ..services.recommendations import recommend

router = APIRouter()


@router.post("/recommendations")
def recommendations(request: RecommendationRequest) -> RecommendationResponse:
    return recommend(request)
