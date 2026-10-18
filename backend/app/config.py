import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db: str = os.getenv("MONGODB_DB", "remind")
    robot_worker_url: str = os.getenv("ROBOT_WORKER_URL", "http://localhost:8001")
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    gemini_fallback_model: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")  # used on 429/503
    # After-session fact extraction (memory.digest_session). Lite: ~0.5 s, where flash-latest took 27-40 s (2026-10-18).
    memory_digest_model: str = os.getenv("MEMORY_DIGEST_MODEL", "gemini-flash-lite-latest")
    gemini_live_model: str = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
    gemini_live_voice: str = os.getenv("GEMINI_LIVE_VOICE", "Aoede")
    gemini_live_temperature: float = float(os.getenv("GEMINI_LIVE_TEMPERATURE", "0.6"))
    # Backstop only: counts audio tokens (~11 per spoken word) and cuts replies mid-sentence. 200 truncated ~40% of
    # replies in scripts/eval_live.py; 800 is ~70 words, above the prompt's ~30-word target. 0 = unset.
    gemini_live_max_output_tokens: int = int(os.getenv("GEMINI_LIVE_MAX_OUTPUT_TOKENS", "800"))
    gemini_live_vad: str = os.getenv("GEMINI_LIVE_VAD", "default")  # default | fast | legacy (see live.VAD_PRESETS)
    gemini_live_remind_every: int = int(os.getenv("GEMINI_LIVE_REMIND_EVERY", "8"))  # user turns between brevity reminders
    gemini_live_remind_words: int = int(os.getenv("GEMINI_LIVE_REMIND_WORDS", "40"))  # remind if the last 2 replies exceed this
    gemini_live_url: str = os.getenv(
        "GEMINI_LIVE_URL",
        "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
    )
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # any voice in your library
    elevenlabs_model: str = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    # Backboard: the voice call goes through Backboard Realtime, which keeps long-term patient memory (voice/upstreams.py,
    # voice/memory.py). Unset key = direct Gemini Live with no memory writes; sessions still use the care profile.
    backboard_api_key: str = os.getenv("BACKBOARD_API_KEY", "")
    backboard_url: str = os.getenv("BACKBOARD_URL", "https://app.backboard.io/api")
    backboard_realtime_url: str = os.getenv("BACKBOARD_REALTIME_URL", "wss://app.backboard.io/api/threads/realtime")
    backboard_realtime_model: str = os.getenv("BACKBOARD_REALTIME_MODEL", os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live"))
    backboard_timeout_s: float = float(os.getenv("BACKBOARD_TIMEOUT_S", "3.0"))  # session start waits at most this long
    voice_transport: str = os.getenv("VOICE_TRANSPORT", "")  # backboard | gemini; empty = backboard when its key is set


settings = Settings()
