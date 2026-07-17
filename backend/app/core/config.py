from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str
    database_url: str

    # OpenAI model config
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chat_model: str = "gpt-4o"
    chat_temperature: float = 0.1

    # Chunking config
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # Retrieval config
    top_k_chunks: int = 5

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
