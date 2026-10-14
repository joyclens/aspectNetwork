from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr, ValidationInfo, field_validator

from bot.core.ids import App, Secrets
from bot.services.roblox import normalize_cookie


class Settings(BaseModel):
    discord_token: SecretStr
    command_prefix: str = "!"
    postgres_dsn: SecretStr
    roblox_cookie: SecretStr
    roblox_group_id: int = Field(default=719648172, gt=0)
    dock_api_key: SecretStr | None = None
    dock_pid: str | None = None
    cookie_api_key: SecretStr | None = None
    roblox_api_key: SecretStr | None = None
    roblox_universe_id: int = Field(default=8848357152, gt=0)

    @field_validator("command_prefix")
    @classmethod
    def prefix_ok(cls, value: str) -> str:
        if not 1 <= len(value) <= 5 or any(char.isspace() for char in value):
            raise ValueError("invalid prefix")
        return value

    @field_validator("discord_token", "roblox_cookie", "postgres_dsn", mode="before")
    @classmethod
    def secret_ok(cls, value: object, info: ValidationInfo) -> SecretStr:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        if info.field_name == "roblox_cookie":
            raw = normalize_cookie(str(raw))
        else:
            raw = raw.strip()
        if len(raw) < 8 or any(char in raw for char in "\r\n"):
            raise ValueError("invalid secret")
        if info.field_name == "postgres_dsn" and not raw.startswith(
            ("postgres://", "postgresql://")
        ):
            raise ValueError("invalid postgres dsn")
        return SecretStr(raw)

    @field_validator("dock_api_key", "cookie_api_key", "roblox_api_key", mode="before")
    @classmethod
    def optional_key_ok(cls, value: object) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        raw = raw.strip()
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


def load_settings() -> Settings:
    return Settings(
        discord_token=Secrets.discord_token,
        command_prefix=App.command_prefix,
        postgres_dsn=Secrets.postgres_dsn,
        roblox_cookie=Secrets.roblox_cookie,
        roblox_group_id=App.roblox_group_id,
        dock_api_key=Secrets.dock_api_key,
        dock_pid=Secrets.dock_pid,
        cookie_api_key=Secrets.cookie_api_key,
        roblox_api_key=Secrets.roblox_api_key or None,
        roblox_universe_id=App.roblox_universe_id,
    )
