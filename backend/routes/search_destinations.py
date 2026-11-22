from typing import Annotated

from fastapi import APIRouter, Query

from ..catalog import destinations, search
from ..models import Destination
from ..schemas.search import SearchPage, SearchParams

router = APIRouter()


@router.get("/destinations/search")
def search_destinations(params: Annotated[SearchParams, Query()]) -> SearchPage[Destination]:
    return search(destinations, params)
