from pydantic import BaseModel, Field


class Destination(BaseModel):
    id: str
    name: str


class Place(BaseModel):
    id: str
    name: str
    tripworld_region_id: str = Field(description="ID of the region in the TripWorld destination catalog.")
    lng: float
    lat: float
