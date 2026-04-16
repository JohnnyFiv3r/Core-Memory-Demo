from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
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
