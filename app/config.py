from functools import lru_cache
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Export .env into os.environ so LangSmith/LangChain tracing picks up LANGCHAIN_* vars.
load_dotenv()


class Settings(BaseSettings):
    mesh_api_key: str = ""
    mesh_base_url: str = "https://api.meshapi.ai/v1"
    mesh_chat_model: str = "openai/gpt-4o-mini"
    mesh_embedding_model: str = "openai/text-embedding-3-small"
    database_url: str = "sqlite:///./smartreco.db"
    secret_key: str = "development-only-change-me"
    admin_email: str = "admin@smartreco.local"
    admin_password: str = "ChangeMe123!"
    chroma_path: str = "./chroma_data"
    reco_min_score: int = 8
    reco_cooldown_minutes: int = 20
    enable_scheduler: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "SmartReco <recommendations@example.com>"
    smtp_use_tls: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

