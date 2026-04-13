from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routes.health import router as health_router
from app.routes.demo import router as demo_router


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
    allow_origins=[settings.allowed_origin],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(health_router)
app.include_router(demo_router)


@app.on_event('startup')
def on_startup():
    ensure_roots_writable()


@app.get('/')
def root():
    return {
        'ok': True,
        'service': settings.app_name,
        'env': settings.app_env,
        'roots': [str(Path(p)) for p in settings.roots],
    }
