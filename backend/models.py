from pydantic import BaseModel, Field


class Destination(BaseModel):
    id: str
    name: str
    country: str | None = None
    canonical_name: str | None = None
    canonical_metro_label: str | None = None
    matched_alias: str | None = None


class Place(BaseModel):
    id: str
    name: str
    tripworld_region_id: str = Field(description="ID of the region in the TripWorld destination catalog.")
    locality: str | None = None
    category: str | None = None
    lng: float
    lat: float
