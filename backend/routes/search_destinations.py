from typing import Annotated

from fastapi import APIRouter, Query

from ..destination_catalog import Catalog
from ..models import Destination
from ..schemas.search import SearchPage, SearchParams

router = APIRouter()


@router.get("/destinations/search")
def search_destinations(params: Annotated[SearchParams, Query()]) -> SearchPage[Destination]:
    with Catalog() as catalog:
        page = catalog.search_page(params.q, limit=params.limit, offset=params.offset)
    return SearchPage(
        items=[Destination(
            id=row["region_id"], name=row["matched_alias"] or row["city_name"],
            country=row["country_name"], canonical_name=row["city_name"],
            canonical_metro_label=row["canonical_metro_label"], matched_alias=row["matched_alias"],
        ) for row in page["items"]],
        next_offset=page["next_offset"],
    )
