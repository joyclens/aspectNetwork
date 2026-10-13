from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Emojis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    approve: str = "<:checkmark:1551257148917424128>"
    warn: str = "<:warning:1551256110869127168>"
    error: str = "<:xmark:1551256137419202673>"
    robux: str = "<:robux:1559293111329619991>"
    loading: str = "<:hourglass:1559294195401887774>"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: SecretStr
    discord_guild_id: int = Field(gt=0)
    command_prefix: str = "!"
    postgres_dsn: SecretStr
    roblox_cookie: SecretStr
    roblox_group_id: int = Field(default=719648172, gt=0)
    dock_api_key: SecretStr | None = None
    dock_pid: str | None = None
    cookie_api_key: SecretStr | None = None
    verified_role_id: int | None = Field(default=None, gt=0)
    ticket_support_role_id: int | None = Field(default=None, gt=0)
    ticket_logs_channel_id: int | None = Field(default=None, gt=0)
    emojis: Emojis = Field(default_factory=Emojis)

    @field_validator("command_prefix")
    @classmethod
    def prefix_ok(cls, value: str) -> str:
        if not 1 <= len(value) <= 5 or any(char.isspace() for char in value):
            raise ValueError("invalid prefix")
        return value

    @field_validator("discord_token", "roblox_cookie", "postgres_dsn")
    @classmethod
    def secret_ok(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        raw = value.get_secret_value().strip()
        if len(raw) < 8 or any(char in raw for char in "\r\n"):
            raise ValueError("invalid secret")
        if info.field_name == "postgres_dsn" and not raw.startswith(
            ("postgres://", "postgresql://")
        ):
            raise ValueError("invalid postgres dsn")
        return SecretStr(raw)

    @field_validator("dock_api_key", "cookie_api_key")
    @classmethod
    def optional_key_ok(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if len(raw) < 8 or any(char in raw for char in "\r\n"):
            raise ValueError("invalid secret")
        return SecretStr(raw)

    @field_validator("dock_pid")
    @classmethod
    def dock_pid_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        raw = value.strip()
        if not raw:
            return None
        if any(char in raw for char in "\r\n ") or len(raw) > 64:
            raise ValueError("invalid pid")
        return raw
