from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Core Memory Demo API'
    app_env: str = 'dev'

    allowed_origin: str = 'http://localhost:5173,https://demo.usecorememory.com'

    core_memory_root: str = './var/core-memory'
    core_memory_demo_benchmark_root: str = './var/core-memory-bench'
    core_memory_demo_artifacts_root: str = './var/core-memory-artifacts'

    demo_model_id: str = ''
    demo_context_budget: int = 128000

    demo_auth_enabled: bool = False
    demo_auth_public_read_endpoints: bool = True
    demo_auth0_domain: str = ''
    demo_auth0_audience: str = ''
    demo_auth0_client_id: str = ''
    demo_auth0_scope: str = ''
    demo_auth0_issuer: str = ''
    demo_auth_require_verified_email: bool = False
    demo_admin_emails: str = ''
    demo_auth_jwt_leeway_seconds: int = 30

    abuse_general_max_requests: int = 300
    abuse_general_window_seconds: int = 60
    abuse_chat_max_requests: int = 120
    abuse_chat_window_seconds: int = 60
    abuse_heavy_max_requests: int = 40
    abuse_heavy_window_seconds: int = 300
    abuse_heavy_max_concurrent: int = 1

    seed_max_turns: int = 500
    replay_max_turns: int = 500
    benchmark_limit_max_cases: int = 50
    benchmark_preload_turns_max: int = 400
    benchmark_history_max_rows: int = 300
    benchmark_runs_max_keep: int = 80

    async_jobs_tick_enabled: bool = True
    async_jobs_tick_interval_seconds: int = 60
    async_jobs_tick_initial_delay_seconds: int = 10
    async_jobs_tick_max_compaction: int = 2
    async_jobs_tick_max_side_effects: int = 8
    async_jobs_tick_run_semantic: bool = True

    @property
    def roots(self) -> list[Path]:
        return [
            Path(self.core_memory_root),
            Path(self.core_memory_demo_benchmark_root),
            Path(self.core_memory_demo_artifacts_root),
        ]

    @property
    def cors_allowed_origins(self) -> list[str]:
        raw = str(self.allowed_origin or '').strip()
        out: list[str] = []
        for part in raw.split(','):
            v = part.strip().strip('"').strip("'").rstrip('/')
            if v and v not in out:
                out.append(v)
        if not out:
            out = ['http://localhost:5173', 'https://demo.usecorememory.com']
        return out

    @property
    def auth0_issuer(self) -> str:
        if str(self.demo_auth0_issuer or '').strip():
            issuer = str(self.demo_auth0_issuer or '').strip()
        else:
            domain = str(self.demo_auth0_domain or '').strip().strip('/')
            issuer = f'https://{domain}/' if domain else ''
        if issuer and not issuer.endswith('/'):
            issuer += '/'
        return issuer

    @property
    def admin_emails(self) -> set[str]:
        raw = str(self.demo_admin_emails or '').strip()
        if not raw:
            return set()
        return {x.strip().lower() for x in raw.split(',') if x.strip()}


settings = Settings()
