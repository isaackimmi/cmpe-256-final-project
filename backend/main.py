from fastapi import FastAPI

from .routes import health, recommendations, search_destinations, search_places

app = FastAPI(title="TripWorld API")
app.include_router(health.router)
app.include_router(search_places.router)
app.include_router(search_destinations.router)
app.include_router(recommendations.router)
