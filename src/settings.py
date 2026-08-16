import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()
load_dotenv("api_keys.env")


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("MQTT_ENDPOINT_HOST", os.getenv("MQTT_BROKER_HOST", "")).strip()
    mqtt_port: int = int(os.getenv("MQTT_ENDPOINT_PORT", os.getenv("MQTT_BROKER_PORT", "1883")))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "TEAM_2")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_topic: str = os.getenv("MQTT_TOPIC", "hackathon/team_2/test/telemetry")
    mqtt_tls: bool = os.getenv("MQTT_TLS", "false").lower() == "true"
    mqtt_transport: str = os.getenv("MQTT_TRANSPORT", "tcp").lower()
    mqtt_websocket_path: str = os.getenv("MQTT_WEBSOCKET_PATH", "/mqtt")
    mqtt_keepalive_seconds: int = int(os.getenv("MQTT_KEEPALIVE_SECONDS", "30"))
    mqtt_client_id_prefix: str = os.getenv("MQTT_CLIENT_ID_PREFIX", "farmops-team-2")
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    stale_after_seconds: int = int(os.getenv("STALE_AFTER_SECONDS", "60"))
    database_path: str = os.getenv("DATABASE_PATH", "farmops.db")
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "farmops")
    # LLM 1: Gemini 3.5 Flash-Lite (Dùng cho Irrigation Planning Agent)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    # LLM 2: GPT-OSS 120B #1 (Dùng cho Resource Agent)
    gpt_oss_api_key: str = os.getenv("GPT_OSS_API_KEY", os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")))
    gpt_oss_model: str = os.getenv("GPT_OSS_MODEL", os.getenv("LLM_MODEL", "openai/gpt-oss-120b"))
    gpt_oss_base_url: str = os.getenv("GPT_OSS_BASE_URL", os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"))

    # LLM 3: GPT-OSS 120B #2 (Dùng cho Field IoT Agent)
    gpt_oss_2_api_key: str = os.getenv("GPT_OSS_2_API_KEY", "")
    gpt_oss_2_model: str = os.getenv("GPT_OSS_2_MODEL", "openai/gpt-oss-120b")
    gpt_oss_2_base_url: str = os.getenv("GPT_OSS_2_BASE_URL", "https://openrouter.ai/api/v1")

    # LLM 4: Gemini 3.5 #2 (Dùng cho Farm Coordinator Agent)
    gemini_2_api_key: str = os.getenv("GEMINI_2_API_KEY", "")
    gemini_2_model: str = os.getenv("GEMINI_2_MODEL", "gemini-3.5-flash")

    # Legacy/Fallback compatibility
    llm_api_key: str = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    @property
    def mqtt_is_configured(self) -> bool:
        return bool(
            self.mqtt_host
            and self.mqtt_password
            and self.mqtt_transport in {"tcp", "websockets"}
            and not self.mqtt_host.startswith(("replace-", "tk_"))
            and not self.mqtt_password.startswith("replace-")
        )

settings = Settings()
