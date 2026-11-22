from fastapi import APIRouter

from ..schemas.agent import FeedbackRequest, FeedbackResponse
from ..services.agent import refine

router = APIRouter()


@router.post("/agent/feedback")
async def feedback(request: FeedbackRequest) -> FeedbackResponse:
    return await refine(request)
