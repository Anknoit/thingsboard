"""
Centralised configuration via pydantic-settings.
All values come from environment variables (or .env file).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── NavNet Registry ───────────────────────────────────────────────────────
    registry_url: str = "http://localhost:8080"
    registry_admin_user: str = "admin@navnet.local"
    registry_admin_password: str = "changeme"
    jwt_expiry_seconds: int = 9000  # 2.5 hours

    # ── FastAPI ───────────────────────────────────────────────────────────────
    fastapi_port: int = 8000
    secret_key: str = "change-me"

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str = "claude"  # claude | openai | ollama
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    claude_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"

    # ── Kafka ─────────────────────────────────────────────────────────────────
    kafka_bootstrap: str = "localhost:9092"
    kafka_topics_bms_hvac: str = "navnet.telemetry.bms.hvac"
    kafka_topics_bms_energy: str = "navnet.telemetry.bms.energy"
    kafka_topics_bms_other: str = "navnet.telemetry.bms.other"
    kafka_topics_nms_network: str = "navnet.telemetry.nms.network"
    kafka_topics_nms_infra: str = "navnet.telemetry.nms.infra"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_url: str = "postgresql+asyncpg://p2:changeme@localhost:5432/platform2"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "navnet_kb"

    # ── Anomaly detection ─────────────────────────────────────────────────────
    anomaly_sigma_threshold: float = 3.4
    anomaly_baseline_days: int = 30

    # ── Predictive maintenance ────────────────────────────────────────────────
    lstm_failure_threshold: float = 0.75
    lstm_batch_hour: int = 2

    # ── GNN ───────────────────────────────────────────────────────────────────
    cascade_alarm_count: int = 3
    cascade_window_seconds: int = 60


settings = Settings()
