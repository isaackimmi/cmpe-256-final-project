from typing import Annotated

from fastapi import APIRouter, Query

from ..catalog import destinations, search
from ..schemas.search import SearchParams

router = APIRouter()


@router.get("/destinations/search")
def search_destinations(params: Annotated[SearchParams, Query()]):
    return search(destinations, params)
