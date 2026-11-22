from typing import Annotated

from fastapi import APIRouter, Query

from ..catalog import places, search
from ..schemas.search import SearchParams

router = APIRouter()


@router.get("/places/search")
def search_places(params: Annotated[SearchParams, Query()]):
    return search(places, params)
