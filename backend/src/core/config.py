from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Global configuration for the FastAPI backend.
    Values are read from environment variables or .env file.
    """

    # === PostgreSQL registry ===
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string for registry")

    # === Neo4j admin credentials ===
    NEO4J_ADMIN_URI: str = Field(..., description="Bolt URI for Neo4j admin connection")
    NEO4J_ADMIN_USER: str = Field(..., description="Admin username for Neo4j")
    NEO4J_ADMIN_PASS: str = Field(..., description="Admin password for Neo4j")

    # === Neo4j public connection URI (for tenants/domains to use) ===
    NEO4J_PUBLIC_URI: str = Field(..., description="Public URI shared to provisioned domains")

    # === Encryption key for credentials (AES-GCM / libsodium key) ===
    REGISTRY_ENC_KEY: str = Field(..., description="Encryption key (base64) for storing Neo4j secrets")

    # === Job backend (rq, background, etc.) ===
    JOB_BACKEND: str = Field(default="rq", description="Job backend type: rq or background")

    # === Flags ===
    PROVISION_ASYNC: bool = Field(default=True, description="Enable async provisioning via queue backend")

    # === Internal service token for provisioning endpoint ===
    INTERNAL_PROVISION_TOKEN: str = Field(default="", description="Service token required for internal provisioning calls")

    # === Optional development flags ===
    ENVIRONMENT: str = Field(default="development", description="Environment: development / production / staging")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    
    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """
    Cached singleton getter for Settings.
    Usage:
        from src.core.config import get_settings
        cfg = get_settings()
        print(cfg.DATABASE_URL)
    """
    return Settings()
