from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    claude_api_key: str = ""
    openai_api_key: str = ""

    llm_retry_max: int = 3
    llm_retry_backoff_base: float = 2.0

    # Browser / Codex settings
    browser_headless: bool = True
    # Single source of truth for any `codex exec` invocation timeout (seconds).
    # Used by both `app/tools/llm_tool.py` (text generation) and
    # `app/tools/codex_tool.py` (browser automation), via `app/tools/codex_exec.py`.
    #
    # Sizing notes: the keyword_strategist `classify` step routinely sends a
    # ~10K-token prompt and asks Claude Sonnet to emit ~10K tokens of
    # structured JSON in one shot, which empirically takes 3-7 minutes via the
    # codex CLI. 600s gives comfortable headroom while still aborting truly
    # hung subprocesses. Tune via the `CODEX_TIMEOUT` env var.
    codex_timeout: int = 600
    scrape_max_review_pages: int = 3
    # Max simultaneous competitor scrapes per research phase (listing/Alex/
    # reviews). Bounds concurrent codex CLI subprocesses to avoid overload /
    # rate limits. Set to 1 to fall back to fully sequential scraping.
    research_concurrency: int = 3

    # Listing length limits (Amazon-standard, max-only). Seeded into per-run
    # ListingState.length_limits at create time and enforced by the copywriter
    # round-3 regenerate loop via ComplianceTool.validate.
    title_max_chars: int = 200
    bullet_max_chars: int = 500
    # Total byte budget across all five bullets joined by newlines. This is the
    # binding constraint shown in the UI ("XXXX / 1000 字节"); enforce it so the
    # copywriter regenerates when the combined bullets exceed it.
    bullets_total_max_bytes: int = 1000
    description_max_chars: int = 2000
    st_max_bytes: int = 249
    # Soft minimums: fed back as violations to encourage fuller content, but the
    # copywriter loop ships the last draft after retries, so they never block a
    # run (unlike the hard maximums above). Keep min < max.
    title_min_chars: int = 120
    bullets_total_min_bytes: int = 700
    description_min_chars: int = 1500
    # Max whole-listing regenerations when length/compliance violations remain.
    copywriter_max_retries: int = 5

    artifacts_dir: str = "artifacts/runs"
    checkpoint_db: str = "checkpoints.db"

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env"}


settings = Settings()
