"""Typed application settings loaded from environment variables / `.env`.

Every key mirrors docs/architecture.md §10. Import the cached instance with `get_settings()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM (LiteLLM model strings) ---
    llm_primary: str = "gemini/gemini-3.8-flash"
    llm_fallback: str = "groq/openai/gpt-oss-120b"
    llm_voice_nlu: str = "groq/openai/gpt-oss-20b"
    llm_judge: str = "gemini/gemini-pro-latest"
    eval_llm_judge: bool = False  # opt-in: LLM judge in evals; off = deterministic proxies
    llm_timeout_s: float = 30.0
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    # --- Retrieval (Pillar A) ---
    embed_provider: Literal["local", "gemini"] = "local"
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    top_k: int = Field(5, ge=1, le=20)
    rerank_candidates: int = Field(16, ge=1, le=100)
    min_relevance: float = 0.05  # reranker sigmoid score; calibrated on the golden set (Phase 3)
    extractive_min_score: float = 0.3  # open questions need a stronger match than templates
    rerank_enabled: bool = True
    rag_llm_enabled: bool = True  # LLM router + composer when a key exists; else deterministic
    kb_table: str = "kb_unified"
    hf_offline: bool = True  # load models from the project-local cache only (no network)
    # Lite runtime (Streamlit Community Cloud, ~1 GB RAM): keyword (FTS) retrieval only, no torch
    # or local models; the index auto-builds into its own folder without embeddings.
    kb_lite: bool = False

    # --- Voice (Pillar B) ---
    stt_model: str = "groq/whisper-large-v3-turbo"
    tts_voice: str = "en-IN-NeerjaNeural"
    voice_llm_enabled: bool = False  # opt-in: LLM NLU fallback when rules are unsure
    voice_stt_enabled: bool = False  # opt-in: mic input → Groq Whisper (needs GROQ_API_KEY)
    voice_tts_enabled: bool = False  # opt-in: spoken replies via edge-tts (network call)

    # --- Pulse (M2) ---
    pulse_max_words: int = 250
    pulse_action_ideas: int = 3
    pulse_llm_enabled: bool = False  # opt-in: LLM classifier + summaries/ideas (needs a key)
    pulse_llm_batch: int = Field(25, ge=1, le=100)
    pulse_min_confidence: float = 0.5
    pulse_autobuild: bool = True  # build a pulse from the bundled reviews CSV on first visit

    # --- Time ---
    timezone: str = "Asia/Kolkata"

    # --- MCP / HITL (Pillar C) ---
    adapter_mode: Literal["mock", "google"] = "mock"
    mcp_server_target: str = "inprocess"
    mcp_call_timeout_s: float = 10.0
    google_prebooking_doc_id: str | None = None
    google_calendar_id: str = "primary"
    google_service_account_file: Path | None = None  # M3 option: service account instead of OAuth
    google_client_secrets_path: Path = ROOT_DIR / "secrets" / "client_secret.json"
    google_token_path: Path = ROOT_DIR / "secrets" / "token.json"
    advisor_email: str = "advisor@example.com"

    # --- Safety / observability (Phase 1) ---
    # spaCy pipeline for PERSON NER. "blank:en" = regex/context-only (no download needed);
    # set to e.g. "en_core_web_lg" only after installing that model explicitly.
    pii_nlp_model: str = "blank:en"
    pii_score_threshold: float = Field(0.4, ge=0.0, le=1.0)
    guard_llm_enabled: bool = True  # LLM intent classifier when no rule fires
    phoenix_tracing: bool = False
    log_level: str = "INFO"

    # --- Paths ---
    data_dir: Path = ROOT_DIR / "data"
    db_path: Path = ROOT_DIR / "data" / "artifacts" / "suite.db"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def lancedb_dir(self) -> Path:
        return self.data_dir / ("lancedb_lite" if self.kb_lite else "lancedb")

    @property
    def models_dir(self) -> Path:
        return ROOT_DIR / ".models" / "hf"


@lru_cache
def get_settings() -> Settings:
    return Settings()
