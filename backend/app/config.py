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
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # any voice in your library
    elevenlabs_model: str = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    xai_voice_url: str = os.getenv("XAI_VOICE_URL", "wss://api.x.ai/v1/realtime")
    xai_voice_model: str = os.getenv("XAI_VOICE_MODEL", "grok-voice-latest")
    xai_voice: str = os.getenv("XAI_VOICE", "eve")
    xai_model: str = os.getenv("XAI_MODEL", "")  # confirm the model name with SpaceXAI mentors


settings = Settings()
