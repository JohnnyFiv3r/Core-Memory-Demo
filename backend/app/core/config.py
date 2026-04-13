from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Core Memory Demo API'
    app_env: str = 'dev'

    allowed_origin: str = 'http://localhost:5173'

    core_memory_root: str = './var/core-memory'
    core_memory_demo_benchmark_root: str = './var/core-memory-bench'
    core_memory_demo_artifacts_root: str = './var/core-memory-artifacts'

    demo_model_id: str = ''
    demo_context_budget: int = 10000

    @property
    def roots(self) -> list[Path]:
        return [
            Path(self.core_memory_root),
            Path(self.core_memory_demo_benchmark_root),
            Path(self.core_memory_demo_artifacts_root),
        ]


settings = Settings()
