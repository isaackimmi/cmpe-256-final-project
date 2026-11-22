from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .routes import agent, health, recommendations, search_destinations, search_places
from .validation import request_validation_error

app = FastAPI(title="TripWorld API")
app.add_exception_handler(RequestValidationError, request_validation_error)
app.include_router(health.router)
app.include_router(agent.router)
app.include_router(search_places.router)
app.include_router(search_destinations.router)
app.include_router(recommendations.router)
