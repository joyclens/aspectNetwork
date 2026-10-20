from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RateLimitMeta(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = Field(default=None, alias="resetAt")
    retry_after: int | None = Field(default=None, alias="retryAfter")
    scope: str | None = None
    bucket: str | None = None


class V2Meta(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    request_id: str = Field(alias="requestId")
    version: str
    rate_limit: RateLimitMeta = Field(alias="rateLimit")
    tier: str | None = None


class V2ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    details: dict[str, Any] | None = None


class V2ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: int
    error: V2ErrorBody
    meta: V2Meta
    timestamp: datetime


class V2SuccessEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: int
    data: Any = None
    meta: V2Meta
    timestamp: datetime


class DiscordLookup(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    discord_id: str = Field(alias="discordId")
    roblox_id: str = Field(alias="robloxId")
    resolved: dict[str, Any] | None = None


class BulkItemError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None
    status: int | None = None


class BulkLookupItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input: dict[str, Any]
    found: bool
    data: dict[str, Any] | None = None
    error: BulkItemError | None = None


class BulkLookupResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    results: list[BulkLookupItem]
    count: int
    found_count: int = Field(alias="foundCount")
    not_found_count: int = Field(alias="notFoundCount")
    error_count: int = Field(alias="errorCount")
    resolved: bool


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    pid: str
    client_id: str = Field(alias="clientId")
    status: str
    expires_at: datetime = Field(alias="expiresAt")
    verify_url: str = Field(alias="verifyUrl")
    reused_existing: bool = Field(alias="reusedExisting")
    guild_id: str | None = Field(default=None, alias="guildId")
    status_reason: str | None = Field(default=None, alias="statusReason")

    @property
    def sid(self) -> str:
        return self.id


class SessionResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    discord_id: str | None = Field(default=None, alias="discordId")
    roblox_id: str | None = Field(default=None, alias="robloxId")
    verified_at: datetime | None = Field(default=None, alias="verifiedAt")
    link_changed: bool | None = Field(default=None, alias="linkChanged")
    previous_roblox_id: str | None = Field(default=None, alias="previousRobloxId")
    link_version: int | None = Field(default=None, alias="linkVersion")
    link_hash: str | None = Field(default=None, alias="linkHash")


class SessionState(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    pid: str
    client_id: str = Field(alias="clientId")
    status: str | None = None
    expires_at: datetime = Field(alias="expiresAt")
    verify_url: str = Field(alias="verifyUrl")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    terminal_at: datetime | None = Field(default=None, alias="terminalAt")
    result: SessionResult | None = None
    guild_id: str | None = Field(default=None, alias="guildId")
    status_reason: str | None = Field(default=None, alias="statusReason")
