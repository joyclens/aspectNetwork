from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TypeVar, overload

import aiohttp
import discord
import jishaku
from discord.ext import commands

from bot import __version__
from bot.core.config import Settings
from bot.core.database import Database, connect
from bot.core.ux import print_banner
from bot.services.cookie import Cookie
from bot.services.dock import Dock
from bot.services.roblox import Roblox, RobloxError
from bot.shared.context import Context, PromptDeclined
from bot.shared.errors import (
    DatabaseUnavailable,
    deliver_trace,
    error_mentions,
    error_notice,
    remember_error,
)
from bot.shared.http import session

logger = logging.getLogger("aspect")

ContextT = TypeVar("ContextT", bound=commands.Context[Any])


jishaku.flags.RETAIN = True
jishaku.flags.NO_DM_TRACEBACK = False


def _discover(folder: str) -> list[str]:
    root = Path(__file__).resolve().parents[1] / folder
    return [
        f"bot.{folder}.{path.stem}"
        for path in sorted(root.glob("*.py"))
        if path.name != "__init__.py" and not path.name.startswith("_")
    ]


class Aspect(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=settings.command_prefix,
            case_insensitive=True,
            strip_after_prefix=True,
            intents=discord.Intents.all(),
            allowed_mentions=discord.AllowedMentions.none(),
            help_command=None,
            max_messages=300,
        )
        self.settings = settings
        self.session: aiohttp.ClientSession | None = None
        self.db: Database | None = None
        self.roblox: Roblox | None = None
        self.dock: Dock | None = None
        self.cookie: Cookie | None = None
        self.db_version = ""
        self._locks: dict[str, asyncio.Lock] = {}
        self.traceback: dict[str, BaseException] = {}
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
        self.session = session(timeout=40)
        self.db, self.db_version = await connect(self.settings.postgres_dsn.get_secret_value())
        self.roblox = Roblox(
            self.settings.roblox_cookie.get_secret_value(),
            self.settings.roblox_group_id,
            self.session,
        )
        await self.roblox.start()
        await asyncio.gather(self._check_roblox(), self._start_dock(), self._start_cookie())
        await self._load_extensions()
        await self.load_extension("jishaku")
   

    async def on_ready(self) -> None:
        if self._banner_printed or self.user is None:
            return
        self._banner_printed = True
        print_banner(self)

    async def on_interaction(self, interaction: discord.Interaction[Any]) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        payload: Any = interaction.data
        custom_id = payload.get("custom_id") if isinstance(payload, dict) else ""
        logger.info(
            "Component %s from %s in guild %s",
            custom_id or "(none)",
            interaction.user.id,
            interaction.guild_id,
        )

    async def close(self) -> None:
        await super().close()
        if self._resources_closed:
            return
        self._resources_closed = True
        if self.roblox is not None:
            await self.roblox.close()
        if self.dock is not None:
            await self.dock.close()
        if self.cookie is not None:
            await self.cookie.close()
        if self.session is not None and not self.session.closed:
            await self.session.close()
        if self.db is not None:
            await self.db.close()

    async def _load_extensions(self) -> None:
        for module in _discover("cogs") + _discover("events"):
            try:
                await self.load_extension(module)
            except commands.ExtensionError:
                logger.error("Error loading extension %s", module, exc_info=True)
                continue
            cog = list(self.cogs.values())[-1] if self.cogs else None
            if cog is None:
                logger.info("Loaded %s", module)
                continue
            logger.info(
                "Loaded %s with %s commands and %s events",
                cog.qualified_name,
                len(set(cog.walk_commands())),
                len(cog.get_listeners()),
            )

    async def _on_command_error(
        self,
        context: commands.Context[Any],
        exception: commands.CommandError,
    ) -> None:
        if not isinstance(context, Context) or isinstance(exception, commands.CommandNotFound):
            return
        if isinstance(exception, commands.NotOwner):
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
            if isinstance(exception, DatabaseUnavailable):
                code = remember_error(self.traceback, exception, where="Database")
                await context.warn(error_notice(code), allowed_mentions=error_mentions())
                if await self.is_owner(context.author):
                    await deliver_trace(context.author, self.settings, exception)
                return
            if isinstance(exception, commands.CheckFailure):
                await context.warn("You cannot use that here.")
                return
            code = remember_error(self.traceback, original, where="Command")
            await context.warn(error_notice(code), allowed_mentions=error_mentions())
            if await self.is_owner(context.author):
                await deliver_trace(context.author, self.settings, original)
        except discord.HTTPException:
            remember_error(self.traceback, original, where="Command reply")

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
        if self.session is None:
            logger.warning("Dock verification is missing its http session")
            return
        self.dock = Dock(key.get_secret_value(), pid, self.session)
        await self.dock.start()

    async def _start_cookie(self) -> None:
        key = self.settings.cookie_api_key
        if key is None:
            return
        if self.session is None:
            logger.warning("Cookie transcripts are missing their http session")
            return
        self.cookie = Cookie(key.get_secret_value(), self.session)

    async def _sync_commands(self) -> None:
        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.HTTPException:
            logger.exception("Command sync failed")
            return
        logger.info("Synced %s commands", len(synced))
