import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


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
