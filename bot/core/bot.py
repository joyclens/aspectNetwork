from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TypeVar, overload

import discord
from discord.ext import commands

from bot import __version__
from bot.core.config import Settings
from bot.core.database import Database, connect
from bot.core.ux import print_banner
from bot.services.dock import Dock
from bot.services.roblox import Roblox, RobloxError
from bot.shared.context import Context, PromptDeclined

logger = logging.getLogger("aspect")

ContextT = TypeVar("ContextT", bound=commands.Context[Any])

_EXTENSION_ROOT = Path(__file__).resolve().parents[1] / "extensions"
_EXTENSION_PACKAGES = ("commands", "events")


def _discover_extensions() -> list[str]:
    names: list[str] = []
    for package in _EXTENSION_PACKAGES:
        folder = _EXTENSION_ROOT / package
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.py")):
            if path.name.startswith("_"):
                continue
            relative = path.relative_to(folder).with_suffix("")
            dotted = ".".join(relative.parts)
            names.append(f"bot.extensions.{package}.{dotted}")
    return names


def _log_error(message: str, error: BaseException) -> None:
    logger.error(message, exc_info=(type(error), error, error.__traceback__))


class Aspect(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=settings.command_prefix,
            intents=discord.Intents.all(),
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
        )
        self.settings = settings
        self.db: Database | None = None
        self.roblox: Roblox | None = None
        self.dock: Dock | None = None
        self.db_version = ""
        self._locks: dict[str, asyncio.Lock] = {}
        self._banner_printed = False
        self._resources_closed = False
        self.add_listener(self._on_command_error, "on_command_error")

    @property
    def version(self) -> str:
        return f"aspect/v{__version__}"

    def lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    @overload
    async def get_context(
        self,
        origin: discord.Message | discord.Interaction[Any],
        /,
    ) -> Context: ...

    @overload
    async def get_context(
        self,
        origin: discord.Message | discord.Interaction[Any],
        /,
        *,
        cls: type[ContextT],
    ) -> ContextT: ...

    async def get_context(
        self,
        origin: discord.Message | discord.Interaction[Any],
        /,
        *,
        cls: type[commands.Context[Any]] = Context,
    ) -> Any:
        return await super().get_context(origin, cls=cls)

    async def setup_hook(self) -> None:
        self.db, self.db_version = await connect(self.settings.postgres_dsn.get_secret_value())
        self.roblox = Roblox(
            self.settings.roblox_cookie.get_secret_value(),
            self.settings.roblox_group_id,
        )
        await self.roblox.start()
        await self._check_roblox()
        await self._start_dock()
        extensions = _discover_extensions()
        for extension in extensions:
            await self.load_extension(extension)
        logger.info("Loaded %s extensions", len(extensions))
        await self._sync_commands()

    async def on_ready(self) -> None:
        if self._banner_printed or self.user is None:
            return
        self._banner_printed = True
        print_banner(self)

    async def close(self) -> None:
        if not self._resources_closed:
            self._resources_closed = True
            if self.roblox is not None:
                await self.roblox.close()
            if self.dock is not None:
                await self.dock.close()
            if self.db is not None:
                await self.db.close()
        await super().close()

    async def _on_command_error(
        self,
        context: commands.Context[Any],
        exception: commands.CommandError,
    ) -> None:
        if not isinstance(context, Context) or isinstance(exception, commands.CommandNotFound):
            return
        original: BaseException = exception
        if isinstance(exception, commands.CommandInvokeError):
            original = exception.original
        try:
            if isinstance(exception, commands.CommandOnCooldown):
                wait = f"{exception.retry_after:.0f}"
                await context.warn(f"Slow down. Try again in {wait}s.")
                return
            if isinstance(exception, commands.MissingPermissions | commands.BotMissingPermissions):
                await context.warn("You do not have permission to use that.")
                return
            if isinstance(original, PromptDeclined):
                await context.warn("Confirmation was not accepted.")
                return
            if isinstance(exception, commands.UserInputError):
                await context.warn("That input is not valid.")
                return
            if isinstance(exception, commands.CheckFailure):
                await context.warn("You cannot use that here.")
                return
            if isinstance(original, RobloxError):
                logger.warning("Roblox request failed status=%s", original.status)
                await context.warn("Roblox could not complete that request.")
                return
            _log_error("Command failed", original)
            await context.warn("Something went wrong.")
        except discord.HTTPException:
            _log_error("Failed to send an error reply", original)

    async def _check_roblox(self) -> None:
        if self.roblox is None:
            return
        try:
            account = await self.roblox.authenticated()
        except RobloxError as exc:
            logger.error("Roblox authentication failed status=%s", exc.status)
            return
        logger.info("Roblox session ready for %s", account.name)

    async def _start_dock(self) -> None:
        key = self.settings.dock_api_key
        pid = self.settings.dock_pid
        if key is None or pid is None:
            if key is not None or pid is not None:
                logger.warning("Dock verification is missing its api key or pid")
            return
        self.dock = Dock(key.get_secret_value(), pid)
        await self.dock.start()

    async def _sync_commands(self) -> None:
        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.HTTPException:
            logger.exception("Command sync failed")
            return
        logger.info("Synced %s commands", len(synced))
