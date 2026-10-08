"""
config.py — Application configuration loaded from environment / .env file.
All settings are typed and validated by pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object. Values are read from .env (or environment)."""

    # OpenAI
    openai_api_key: str
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # Chunking
    chunk_size: int = 800       # target characters per chunk
    chunk_overlap: int = 150    # overlap between consecutive chunks

    # Retrieval
    top_k: int = 4              # number of chunks to retrieve per query
    min_score: float = 0.30     # minimum cosine similarity (0-1) to keep a chunk

    # Paths
    chroma_db_path: str = "./chroma_db"
    upload_dir: str = "./uploads"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Singleton — import this everywhere
settings = Settings()
