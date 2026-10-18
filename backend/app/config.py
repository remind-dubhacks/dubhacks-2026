import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db: str = os.getenv("MONGODB_DB", "remind")
    robot_worker_url: str = os.getenv("ROBOT_WORKER_URL", "http://localhost:8001")
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    # Grok (xAI) is optional; without a key the rule-based agent handles every turn.
    xai_api_key: str = os.getenv("XAI_API_KEY", "")
    xai_base_url: str = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    xai_model: str = os.getenv("XAI_MODEL", "")  # confirm the model name with SpaceXAI mentors


settings = Settings()
