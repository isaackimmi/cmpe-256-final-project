from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .destination_catalog import Catalog
from .routes import health, recommendations, search_destinations, search_places
from .validation import request_validation_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail during startup instead of serving a silently empty/missing catalog.
    with Catalog():
        pass
    yield


app = FastAPI(title="TripWorld API", lifespan=lifespan)
app.add_exception_handler(RequestValidationError, request_validation_error)
app.include_router(health.router)
app.include_router(search_places.router)
app.include_router(search_destinations.router)
app.include_router(recommendations.router)
