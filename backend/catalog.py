from typing import TypeVar

from .models import Destination, Place
from .schemas.search import SearchPage, SearchParams

CatalogItem = TypeVar("CatalogItem", Destination, Place)


# Synthetic catalog for frontend integration until the Colab export is available.
destinations = [
    Destination(id="demo-kyoto", name="Kyoto (demo)"),
    Destination(id="demo-maui", name="Maui (demo)"),
]
places = [
    Place(id="demo-garden", name="Demo Garden", tripworld_region_id="demo-kyoto",
          lng=135.78, lat=35.02),
    Place(id="demo-market", name="Demo Market", tripworld_region_id="demo-kyoto",
          lng=135.76, lat=35.00),
    Place(id="demo-park", name="Demo Park", tripworld_region_id="demo-maui",
          lng=-156.47, lat=20.89),
]


def search(items: list[CatalogItem], params: SearchParams) -> SearchPage[CatalogItem]:
    term = params.q.strip().casefold()
    matches = sorted((item for item in items if term and term in item.name.casefold()),
                     key=lambda item: (item.name.casefold(), item.id))
    end = params.offset + params.limit
    return SearchPage(
        items=matches[params.offset:end],
        next_offset=end if end < len(matches) else None,
    )
