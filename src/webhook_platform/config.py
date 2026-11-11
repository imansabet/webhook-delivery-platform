from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    admin_token: SecretStr
    allow_private_destinations: bool = False


class KafkaSettings(DatabaseSettings):
    kafka_bootstrap_servers: str = "localhost:9092"
    deliveries_topic: str = "deliveries"


class RelaySettings(KafkaSettings):
    relay_batch_size: int = Field(default=100, ge=1, le=1000)
    relay_poll_interval_seconds: float = Field(default=1.0, gt=0)


class WorkerSettings(KafkaSettings):
    consumer_group: str = "delivery-workers"
    worker_concurrency: int = Field(default=10, ge=1, le=100)
    worker_batch_size: int = Field(default=50, ge=1, le=500)
    allow_private_destinations: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_relay_settings() -> RelaySettings:
    return RelaySettings()


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
