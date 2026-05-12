from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    claude_api_key: str = ""
    openai_api_key: str = ""

    llm_retry_max: int = 3
    llm_retry_backoff_base: float = 2.0
    llm_timeout: int = 60

    # Browser / Codex settings
    browser_headless: bool = True
    codex_timeout: int = 120
    scrape_max_review_pages: int = 3

    st_max_bytes: int = 249

    artifacts_dir: str = "artifacts/runs"
    checkpoint_db: str = "checkpoints.db"

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env"}


settings = Settings()
