import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = os.getenv("MQTT_BROKER_HOST", "")
    mqtt_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "TEAM_2")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_topic: str = os.getenv("MQTT_TOPIC", "hackathon/team_2/test/telemetry")
    mqtt_tls: bool = os.getenv("MQTT_TLS", "false").lower() == "true"
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    stale_after_seconds: int = int(os.getenv("STALE_AFTER_SECONDS", "300"))
    database_path: str = os.getenv("DATABASE_PATH", "farmops.db")
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "farmops")


settings = Settings()
