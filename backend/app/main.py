import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from core_memory.runtime.jobs import run_async_jobs

from app.core.config import settings
from app.core.state_fallback import safe_state_fallback
from app.routes.health import router as health_router
from app.routes.demo import public_router as demo_public_router
from app.routes.demo import router as demo_router
from app.routes.inspect import router as inspect_router


logger = logging.getLogger(__name__)
_async_jobs_stop = threading.Event()
_async_jobs_thread: threading.Thread | None = None


def ensure_roots_writable() -> None:
    for root in settings.roots:
        root.mkdir(parents=True, exist_ok=True)
        test_file = root / '.write_test'
        try:
            test_file.write_text('ok', encoding='utf-8')
            test_file.unlink(missing_ok=True)
        except Exception as exc:
            raise RuntimeError(f'root_not_writable:{root}:{exc}')


def _async_jobs_tick_loop() -> None:
    initial_delay = max(0, int(settings.async_jobs_tick_initial_delay_seconds))
    interval = max(5, int(settings.async_jobs_tick_interval_seconds))
    if initial_delay > 0:
        _async_jobs_stop.wait(timeout=float(initial_delay))
    while not _async_jobs_stop.is_set():
        try:
            out = run_async_jobs(
                root=settings.core_memory_root,
                run_semantic=bool(settings.async_jobs_tick_run_semantic),
                max_compaction=max(1, int(settings.async_jobs_tick_max_compaction)),
                max_side_effects=max(1, int(settings.async_jobs_tick_max_side_effects)),
            )
            if not bool(out.get('ok')):
                logger.warning('async_jobs_tick_failed: %s', out)
        except Exception as exc:
            logger.warning('async_jobs_tick_exception: %s', exc)
        _async_jobs_stop.wait(timeout=float(interval))


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
    global _async_jobs_thread
    ensure_roots_writable()
    if bool(settings.async_jobs_tick_enabled):
        _async_jobs_stop.clear()
        t = threading.Thread(target=_async_jobs_tick_loop, name='core-memory-async-jobs-tick', daemon=True)
        t.start()
        _async_jobs_thread = t


@app.on_event('shutdown')
def on_shutdown():
    _async_jobs_stop.set()
    t = _async_jobs_thread
    if t and t.is_alive():
        t.join(timeout=1.0)


@app.get('/')
def root():
    return {
        'ok': True,
        'service': settings.app_name,
        'auth_enabled': bool(settings.demo_auth_enabled),
    }
