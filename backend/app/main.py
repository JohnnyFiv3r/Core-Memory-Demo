from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.state_fallback import safe_state_fallback
from app.routes.health import router as health_router
from app.routes.demo import public_router as demo_public_router
from app.routes.demo import router as demo_router
from app.routes.inspect import router as inspect_router


def ensure_roots_writable() -> None:
    for root in settings.roots:
        root.mkdir(parents=True, exist_ok=True)
        test_file = root / '.write_test'
        try:
            test_file.write_text('ok', encoding='utf-8')
            test_file.unlink(missing_ok=True)
        except Exception as exc:
            raise RuntimeError(f'root_not_writable:{root}:{exc}')


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?usecorememory\.com",
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(health_router)
app.include_router(demo_public_router)
app.include_router(demo_router)
app.include_router(inspect_router)

STATE_PATHS = {'/api/demo/state', '/v1/memory/inspect/state'}


@app.middleware('http')
async def state_error_fallback_middleware(request: Request, call_next):
    path = request.url.path
    try:
        response = await call_next(request)
    except Exception as exc:
        if path in STATE_PATHS:
            return JSONResponse(safe_state_fallback(f'unhandled:{exc}'), status_code=200)
        raise

    if path in STATE_PATHS and int(getattr(response, 'status_code', 200) or 200) >= 500:
        return JSONResponse(safe_state_fallback(f'http_{response.status_code}'), status_code=200)
    return response


@app.on_event('startup')
def on_startup():
    ensure_roots_writable()


@app.get('/')
def root():
    return {
        'ok': True,
        'service': settings.app_name,
        'auth_enabled': bool(settings.demo_auth_enabled),
    }
