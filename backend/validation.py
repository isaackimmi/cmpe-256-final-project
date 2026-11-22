from math import isfinite

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Invalid inputs are echoed in FastAPI's error details. JSON cannot encode infinity or NaN.
    details = jsonable_encoder(
        exc.errors(),
        custom_encoder={float: lambda value: value if isfinite(value) else str(value)},
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": details})
