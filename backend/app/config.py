from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    GEMINI_API_KEY: str = ""
    PRIMARY_MODEL: str = "gemini-3.5-flash"
    FALLBACK_MODEL: str = "gemini-2.5-flash"
    LLM_MAX_RETRIES: int = 1  # retries per model before switching to fallback

    # Vector DB
    WEAVIATE_URL: str = ""
    WEAVIATE_API_KEY: str = ""
    WEAVIATE_COLLECTION: str = "DocChunk"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Relational DB
    DATABASE_URL: str = "sqlite:///./app.db"

    # Auth
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    FRONTEND_URL: str = "http://localhost:5173"

    # Ingestion
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_MB: int = 10
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 120

    # Retrieval
    TOP_K: int = 5
    HYBRID_ALPHA: float = 0.6  # 0 = pure keyword (BM25), 1 = pure vector
    MIN_RELEVANCE: float = 0.25  # cosine gate; below this a chunk is treated as irrelevant

    # Memory
    HISTORY_MESSAGES: int = 6

    # Agent
    AGENT_MAX_STEPS: int = 6
    AGENT_TIMEOUT_S: int = 150
    TOOL_TIMEOUT_S: int = 60


settings = Settings()
