import unicodedata
from typing import TypeVar

from .models import Destination, Place
from .schemas.search import SearchPage, SearchParams

CatalogItem = TypeVar("CatalogItem", Destination, Place)


# Display records for the A1 sample experience. Coordinates are illustrative.
destinations = [
    Destination(id="demo-kyoto", name="Kyoto", country="Japan"),
    Destination(id="demo-london", name="London", country="United Kingdom"),
    Destination(id="demo-maui", name="Maui", country="United States"),
]


def sample_place(id: str, name: str, region: str, locality: str, category: str,
                 lng: float, lat: float) -> Place:
    return Place(id=id, name=name, tripworld_region_id=region, locality=locality,
                 category=category, lng=lng, lat=lat)


places = [
    sample_place("a1-kyocera", "Kyoto City KYOCERA Museum of Art", "demo-kyoto", "Okazaki", "Art & culture", 135.7822, 35.0122),
    sample_place("demo-market", "Nishiki Market", "demo-kyoto", "Nakagyō", "Dining", 135.7648, 35.0050),
    sample_place("demo-garden", "Maruyama Park", "demo-kyoto", "Higashiyama", "Outdoors", 135.7808, 35.0034),
    sample_place("a1-weekenders", "Weekenders Coffee", "demo-kyoto", "Nakagyō", "Café", 135.7643, 35.0067),
    sample_place("a1-seven-dials", "Seven Dials Market", "demo-london", "Covent Garden", "Dining", -.1265, 51.5140),
    sample_place("a1-st-james", "St James’s Park", "demo-london", "Westminster", "Outdoors", -.1337, 51.5028),
    sample_place("a1-gallery", "The National Gallery", "demo-london", "Trafalgar Square", "Art & culture", -.1283, 51.5089),
    sample_place("a1-bar-italia", "Bar Italia", "demo-london", "Soho", "Café", -.1315, 51.5132),
    sample_place("a1-mamas", "Mama’s Fish House", "demo-maui", "Pāʻia, Maui", "Dining", -156.3676, 20.9291),
    sample_place("a1-golf", "Wailea Gold Course", "demo-maui", "Wailea, Maui", "Outdoors", -156.4412, 20.6588),
    sample_place("a1-museum", "Maui Arts & Cultural Center", "demo-maui", "Kahului, Maui", "Art & culture", -156.4934, 20.8949),
    sample_place("a1-garden", "Garden of Eden Arboretum", "demo-maui", "Hāna Highway, Maui", "Outdoors", -156.1730, 20.8705),
    sample_place("a1-coffee", "Akamai Coffee", "demo-maui", "Kīhei, Maui", "Café", -156.4558, 20.7477),
    sample_place("demo-park", "Demo Park", "demo-maui", "Maui", "Outdoors", -156.47, 20.89),
]


def search_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c) and c not in "'’ʻ")


def search(items: list[CatalogItem], params: SearchParams) -> SearchPage[CatalogItem]:
    term = search_text(params.q.strip())
    matches = sorted((item for item in items if term in search_text(item.name)),
                     key=lambda item: (item.name.casefold(), item.id))
    end = params.offset + params.limit
    return SearchPage(
        items=matches[params.offset:end],
        next_offset=end if end < len(matches) else None,
    )
