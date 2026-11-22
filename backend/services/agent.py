import asyncio
import json
import os

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, TypeAdapter

from ..schemas.agent import FeedbackRequest, FeedbackResponse
from .recommendations import build_recommendations, get_candidates


class Adjustment(BaseModel):
    category: str
    weight: float = Field(ge=-1, le=1, allow_inf_nan=False)


async def interpret(votes: list[dict]) -> dict[str, float]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(503, "Gemini feedback is not configured.")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    schema = {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["category", "weight"],
              "properties": {"category": {"type": "STRING"}, "weight": {"type": "NUMBER"}}}}
    prompt = ("Summarize the votes as one weight per observed category, from -1 (dislike) "
              "to 1 (like). Balance conflicting votes. Use only these categories.\n" + json.dumps(votes))
    try:
        async with asyncio.timeout(8), httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema}},
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            items = TypeAdapter(list[Adjustment]).validate_json(parts[-1]["text"])
            weights = {item.category: item.weight for item in items}
            if len(weights) != len(items) or set(weights) != {vote["category"] for vote in votes}:
                raise ValueError("Unexpected categories")
            return weights
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Feedback timed out. Please retry.") from None
    except httpx.HTTPError:
        raise HTTPException(503, "Gemini is unavailable. Please retry.") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise HTTPException(502, "Gemini returned invalid feedback. Please retry.") from None


async def refine(request: FeedbackRequest) -> FeedbackResponse:
    pool = get_candidates(request)
    by_id = {p.id: p for p in pool}
    current = request.current_place_ids
    votes = {v.place_id: v.vote for v in request.feedback}
    if (len(set(current)) != len(current) or len(votes) != len(request.feedback)
            or not (set(current) | set(votes)) <= by_id.keys()):
        raise HTTPException(422, "Duplicate or ineligible place ID.")
    context = [{"place": by_id[i].name, "category": by_id[i].category or "Other", "vote": vote}
               for i, vote in votes.items()]
    weights = await interpret(context) if context else {}
    eligible = [p for p in pool if votes.get(p.id) != "dislike"]
    # The sample places have no model scores. Sort by the user's category
    # preferences from Gemini. Ties keep their original catalog order.
    # TODO(model-serving): Start with each place's Stage 2 score, adjust it
    # for liked or disliked categories, then sort by the adjusted score.
    eligible.sort(key=lambda p: -weights.get(p.category or "Other", 0))
    liked = [i for i in current if votes.get(i) == "like"]
    ordered = [p for p in eligible if p.id not in liked][:10-len(liked)]
    for i in liked:
        ordered.insert(min(current.index(i), len(ordered)), by_id[i])
    result = build_recommendations(ordered, request.visited_place_ids)
    ids = [p.id for p in ordered]
    return FeedbackResponse(**result.model_dump(), added_place_ids=[i for i in ids if i not in current],
                            removed_place_ids=[i for i in current if i not in ids],
                            update_summary=f"{len(ids)} places available after feedback.")
