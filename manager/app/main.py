from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .middleware import RequestIDMiddleware
from .routes import router

app = FastAPI(
    title='Flaghunt Runtime Manager',
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
)


app.add_middleware(RequestIDMiddleware)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, 'request_id', None)
    return JSONResponse(
        status_code=422,
        content={'detail': 'Invalid request', 'request_id': request_id},
        headers={'X-Request-ID': request_id} if request_id else {},
    )
