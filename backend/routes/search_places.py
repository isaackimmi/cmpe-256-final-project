from typing import Annotated

from fastapi import APIRouter, Query

from ..catalog import places, search
from ..models import Place
from ..schemas.search import SearchPage, SearchParams

router = APIRouter()


@router.get("/places/search")
def search_places(params: Annotated[SearchParams, Query()]) -> SearchPage[Place]:
    return search(places, params)
