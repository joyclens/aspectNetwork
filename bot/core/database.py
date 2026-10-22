from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import asyncpg

from bot.services.roblox import Sale, sale_from_raw

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Ticket:
    channel_id: int
    owner_id: int
    claimed_by: int | None
    number: int
    kind: str
    reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SponsoredServer:
    name: str
    invite: str


@dataclass(frozen=True, slots=True)
class Giveaway:
    message_id: int
    guild_id: int
    channel_id: int
    winners: int
    members: list[int]
    finish: datetime
    host_id: int
    title: str
    required_roles: list[int] | None
    ignore_roles: list[int] | None
    required_servers: list[SponsoredServer] | None


@dataclass(frozen=True, slots=True)
class Package:
    id: int
    packager_id: int
    package_type: str
    title: str
    price: int
    description: str
    sell_type: str
    customizable: bool
    storage_channel_id: int | None
    storage_message_id: int | None
    status: str
    reviewer_id: int | None
    gamepass_id: int | None
    forum_channel_id: int | None
    forum_thread_id: int | None
    forum_message_id: int | None
    submission_channel_id: int | None
    submission_message_id: int | None
    showcase_filename: str
    sold_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PackagePurchase:
    id: int
    package_id: int
    buyer_id: int
    buyer_roblox_id: int
    recipient_id: int | None
    kind: str
    status: str
    expires_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PackagePayout:
    id: int
    purchase_id: int
    packager_id: int
    gross: int
    packager_amount: int
    network_amount: int
    status: str
    settled_by: int | None
    settled_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PackagerPayoutSummary:
    packager_id: int
    pending_total: int
    paid_total: int
    pending_count: int


@dataclass(frozen=True, slots=True)
class StickyMessage:
    channel_id: int
    guild_id: int
    message: str
    last_message_id: int | None
    keep_old: bool


@dataclass(frozen=True, slots=True)
class GuildTag:
    guild_id: int
    enabled: bool
    channel_id: int | None
    message: str
    role_ids: list[int]


@dataclass(frozen=True, slots=True)
class PackagerPackageEarnings:
    package_id: int
    title: str
    forum_thread_id: int | None
    forum_message_id: int | None
    sales: int
    earned: int
    pending_sales: int
    pending_total: int
    paid_total: int


@dataclass(frozen=True, slots=True)
class Promotion:
    id: int
    kind: str
    owner_id: int
    roblox_id: int
    transaction_id: int
    status: str
    tier: str
    data: dict[str, Any]
    log_message_id: int | None
    ticket_channel_id: int | None
    slot: date | None
    alerted: bool
    post_url: str | None
    reviewer_id: int | None
    created_at: datetime
    approved_at: datetime | None


def _ids(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, str | bytes | bytearray):
        value = json.loads(value)
    if isinstance(value, list):
        return [int(item) for item in value if not isinstance(item, dict)]
    if isinstance(value, int):
        return [value]
    return None


def _servers(value: Any) -> list[SponsoredServer] | None:
    if value is None:
        return None
    if isinstance(value, str | bytes | bytearray):
        value = json.loads(value)
    if not isinstance(value, list):
        return None
    servers: list[SponsoredServer] = []
    for item in value:
        if isinstance(item, dict) and item.get("name") and item.get("invite"):
            servers.append(SponsoredServer(name=str(item["name"]), invite=str(item["invite"])))
    return servers or None


def _member_ids(value: Any) -> list[int]:
    return _ids(value) or []


def _dump_servers(servers: list[SponsoredServer] | None) -> str | None:
    if not servers:
        return None
    return json.dumps([{"name": server.name, "invite": server.invite} for server in servers])


def _sale(row: Any) -> Sale | None:
    raw = row["raw"]
    if isinstance(raw, str | bytes | bytearray):
        raw = json.loads(raw)
    return sale_from_raw(raw) if isinstance(raw, dict) else None


def _ticket(row: Any) -> Ticket:
    return Ticket(
        channel_id=int(row["channel_id"]),
        owner_id=int(row["owner_id"]),
        claimed_by=int(row["claimed_by"]) if row["claimed_by"] is not None else None,
        number=int(row["number"] or 0),
        kind=str(row["kind"] or "general"),
        reason=str(row["reason"] or ""),
        created_at=row["created_at"],
    )


def _giveaway(row: Any) -> Giveaway:
    return Giveaway(
        message_id=int(row["message_id"]),
        guild_id=int(row["guild_id"]),
        channel_id=int(row["channel_id"]),
        winners=int(row["winners"]),
        members=_member_ids(row["members"]),
        finish=row["finish"],
        host_id=int(row["host_id"]),
        title=str(row["title"]),
        required_roles=_ids(row["required_roles"]),
        ignore_roles=_ids(row["ignore_roles"]),
        required_servers=_servers(row["required_servers"]),
    )


def _package(row: Any) -> Package:
    return Package(
        id=int(row["id"]),
        packager_id=int(row["packager_id"]),
        package_type=str(row["package_type"]),
        title=str(row["title"]),
        price=int(row["price"]),
        description=str(row["description"]),
        sell_type=str(row["sell_type"]),
        customizable=bool(row["customizable"]),
        storage_channel_id=(
            int(row["storage_channel_id"]) if row["storage_channel_id"] is not None else None
        ),
        storage_message_id=(
            int(row["storage_message_id"]) if row["storage_message_id"] is not None else None
        ),
        status=str(row["status"]),
        reviewer_id=int(row["reviewer_id"]) if row["reviewer_id"] is not None else None,
        gamepass_id=int(row["gamepass_id"]) if row["gamepass_id"] is not None else None,
        forum_channel_id=(
            int(row["forum_channel_id"]) if row["forum_channel_id"] is not None else None
        ),
        forum_thread_id=(
            int(row["forum_thread_id"]) if row["forum_thread_id"] is not None else None
        ),
        forum_message_id=(
            int(row["forum_message_id"]) if row["forum_message_id"] is not None else None
        ),
        submission_channel_id=(
            int(row["submission_channel_id"]) if row["submission_channel_id"] is not None else None
        ),
        submission_message_id=(
            int(row["submission_message_id"]) if row["submission_message_id"] is not None else None
        ),
        showcase_filename=str(row["showcase_filename"] or ""),
        sold_at=row["sold_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _purchase(row: Any) -> PackagePurchase:
    return PackagePurchase(
        id=int(row["id"]),
        package_id=int(row["package_id"]),
        buyer_id=int(row["buyer_id"]),
        buyer_roblox_id=int(row["buyer_roblox_id"]),
        recipient_id=int(row["recipient_id"]) if row["recipient_id"] is not None else None,
        kind=str(row["kind"]),
        status=str(row["status"]),
        expires_at=row["expires_at"],
        paid_at=row["paid_at"],
        delivered_at=row["delivered_at"],
        created_at=row["created_at"],
    )


def _payout(row: Any) -> PackagePayout:
    return PackagePayout(
        id=int(row["id"]),
        purchase_id=int(row["purchase_id"]),
        packager_id=int(row["packager_id"]),
        gross=int(row["gross"]),
        packager_amount=int(row["packager_amount"]),
        network_amount=int(row["network_amount"]),
        status=str(row["status"]),
        settled_by=int(row["settled_by"]) if row["settled_by"] is not None else None,
        settled_at=row["settled_at"],
        created_at=row["created_at"],
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _promotion(row: Any) -> Promotion:
    data = row["data"]
    if isinstance(data, str | bytes | bytearray):
        data = json.loads(data)
    return Promotion(
        id=int(row["id"]),
        kind=str(row["kind"]),
        owner_id=int(row["owner_id"]),
        roblox_id=int(row["roblox_id"]),
        transaction_id=int(row["transaction_id"]),
        status=str(row["status"]),
        tier=str(row["tier"]),
        data=data if isinstance(data, dict) else {},
        log_message_id=_optional_int(row["log_message_id"]),
        ticket_channel_id=_optional_int(row["ticket_channel_id"]),
        slot=row["slot"],
        alerted=bool(row["alerted"]),
        post_url=str(row["post_url"]) if row["post_url"] is not None else None,
        reviewer_id=_optional_int(row["reviewer_id"]),
        created_at=row["created_at"],
        approved_at=row["approved_at"],
    )


class _Rollback(Exception):
    pass


class Database:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def close(self) -> None:
        await self._pool.close()

    async def known_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        rows = await self._pool.fetch(
            "SELECT id FROM transactions WHERE id = ANY($1::bigint[])",
            ids,
        )
        return {int(row["id"]) for row in rows}

    async def store_sales(self, group_id: int, sales: list[Sale]) -> None:
        if not sales:
            return
        await self._pool.executemany(
            """
            INSERT INTO transactions (
                id, group_id, kind, amount, currency,
                agent_id, agent_name, agent_type,
                item_id, item_name, item_type,
                pending, created_at, raw
            ) VALUES (
                $1, $2, 'Sale', $3, $4,
                $5, $6, $7,
                $8, $9, $10,
                $11, $12, $13::jsonb
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    sale.id,
                    group_id,
                    sale.amount,
                    sale.currency,
                    sale.agent_id,
                    sale.agent_name,
                    sale.agent_type,
                    sale.item_id,
                    sale.item_name or None,
                    sale.item_type or None,
                    sale.pending,
                    sale.created,
                    json.dumps(sale.raw, separators=(",", ":")),
                )
                for sale in sales
            ],
        )

    async def agent_sales(self, group_id: int, agent_id: int) -> list[Sale]:
        rows = await self._pool.fetch(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale' AND agent_id = $2
            ORDER BY created_at DESC
            """,
            group_id,
            agent_id,
        )
        return [sale for row in rows if (sale := _sale(row))]

    async def agent_bought_gamepass(
        self,
        group_id: int,
        agent_id: int,
        gamepass_id: int,
        *,
        since: datetime | None = None,
    ) -> bool:
        row = await self._pool.fetchrow(
            """
            SELECT 1
            FROM transactions
            WHERE group_id = $1
              AND kind = 'Sale'
              AND agent_id = $2
              AND item_id = $3
              AND ($4::timestamptz IS NULL OR created_at >= $4)
            LIMIT 1
            """,
            group_id,
            agent_id,
            gamepass_id,
            since,
        )
        return row is not None

    async def recent_sale(self, group_id: int) -> Sale | None:
        row = await self._pool.fetchrow(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            group_id,
        )
        return _sale(row) if row else None

    async def highest_sale(self, group_id: int) -> Sale | None:
        row = await self._pool.fetchrow(
            """
            SELECT raw FROM transactions
            WHERE group_id = $1 AND kind = 'Sale'
            ORDER BY amount DESC, created_at DESC
            LIMIT 1
            """,
            group_id,
        )
        return _sale(row) if row else None

    async def sales_summary(
        self,
        group_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[int, int]:
        row = await self._pool.fetchrow(
            """
            SELECT COUNT(*)::bigint AS count, COALESCE(SUM(amount), 0)::bigint AS total
            FROM transactions
            WHERE group_id = $1
              AND kind = 'Sale'
              AND ($2::timestamptz IS NULL OR created_at >= $2)
              AND ($3::timestamptz IS NULL OR created_at < $3)
            """,
            group_id,
            start,
            end,
        )
        if row is None:
            return 0, 0
        return int(row["count"]), int(row["total"])

    async def setting(self, key: str) -> Any:
        raw = await self._pool.fetchval("SELECT value FROM settings WHERE key = $1", key)
        return json.loads(raw) if isinstance(raw, str) else raw

    async def store_setting(self, key: str, value: Any) -> None:
        await self._pool.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            key,
            json.dumps(value),
        )

    async def drop_setting(self, key: str) -> None:
        await self._pool.execute("DELETE FROM settings WHERE key = $1", key)

    async def ticket(self, channel_id: int) -> Ticket | None:
        row = await self._pool.fetchrow(
            """
            SELECT channel_id, owner_id, claimed_by, number, kind, reason, created_at
            FROM tickets
            WHERE channel_id = $1
            """,
            channel_id,
        )
        return _ticket(row) if row else None

    async def open_ticket_count(self, owner_id: int) -> int:
        value = await self._pool.fetchval(
            "SELECT COUNT(*)::bigint FROM tickets WHERE owner_id = $1",
            owner_id,
        )
        return int(value or 0)

    async def next_ticket_number(self) -> int:
        value = await self._pool.fetchval("SELECT nextval('ticket_number_seq')")
        return int(value)

    async def create_ticket(
        self,
        channel_id: int,
        owner_id: int,
        number: int,
        kind: str,
        reason: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO tickets (channel_id, owner_id, number, kind, reason)
            VALUES ($1, $2, $3, $4, $5)
            """,
            channel_id,
            owner_id,
            number,
            kind,
            reason,
        )

    async def claim_ticket(self, channel_id: int, user_id: int) -> bool:
        row = await self._pool.fetchrow(
            """
            UPDATE tickets
            SET claimed_by = $1
            WHERE channel_id = $2 AND claimed_by IS NULL
            RETURNING channel_id
            """,
            user_id,
            channel_id,
        )
        if row is None:
            return False
        await self._pool.execute(
            "INSERT INTO ticket_claims (user_id, channel_id) VALUES ($1, $2)",
            user_id,
            channel_id,
        )
        return True

    async def unclaim_ticket(self, channel_id: int) -> None:
        await self._pool.execute(
            "UPDATE tickets SET claimed_by = NULL WHERE channel_id = $1",
            channel_id,
        )

    async def delete_ticket(self, channel_id: int) -> None:
        await self._pool.execute("DELETE FROM tickets WHERE channel_id = $1", channel_id)

    async def ticket_leaderboard(self, limit: int = 10) -> list[tuple[int, int]]:
        rows = await self._pool.fetch(
            """
            SELECT user_id, COUNT(*)::bigint AS claims
            FROM ticket_claims
            GROUP BY user_id
            ORDER BY claims DESC, user_id ASC
            LIMIT $1
            """,
            limit,
        )
        return [(int(row["user_id"]), int(row["claims"])) for row in rows]

    async def giveaway(self, guild_id: int, message_id: int) -> Giveaway | None:
        row = await self._pool.fetchrow(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE guild_id = $1 AND message_id = $2
            """,
            guild_id,
            message_id,
        )
        return _giveaway(row) if row else None

    async def giveaways(self, guild_id: int) -> list[Giveaway]:
        rows = await self._pool.fetch(
            """
            SELECT message_id, guild_id, channel_id, winners, members, finish, host_id,
                   title, required_roles, ignore_roles, required_servers
            FROM giveaways
            WHERE guild_id = $1
            ORDER BY finish ASC
            """,
            guild_id,
        )
        return [_giveaway(row) for row in rows]

    async def active_giveaway_count(self, guild_id: int) -> int:
        value = await self._pool.fetchval(
            "SELECT COUNT(*)::bigint FROM giveaways WHERE guild_id = $1",
            guild_id,
        )
        return int(value or 0)

    async def take_expired_giveaway(self, now: datetime) -> Giveaway | None:
        row = await self._pool.fetchrow(
            """
            DELETE FROM giveaways
            WHERE ctid = (
                SELECT ctid FROM giveaways
                WHERE finish <= $1
                ORDER BY finish ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING message_id, guild_id, channel_id, winners, members, finish, host_id,
                      title, required_roles, ignore_roles, required_servers
            """,
            now,
        )
        return _giveaway(row) if row else None

    async def create_giveaway(
        self,
        *,
        message_id: int,
        guild_id: int,
        channel_id: int,
        winners: int,
        finish: datetime,
        host_id: int,
        title: str,
        required_roles: list[int] | None,
        ignore_roles: list[int] | None,
        required_servers: list[SponsoredServer] | None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO giveaways (
                message_id, guild_id, channel_id, winners, members, finish, host_id, title,
                required_roles, ignore_roles, required_servers
            ) VALUES (
                $1, $2, $3, $4, '[]'::jsonb, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10::jsonb
            )
            """,
            message_id,
            guild_id,
            channel_id,
            winners,
            finish,
            host_id,
            title,
            json.dumps(required_roles) if required_roles else None,
            json.dumps(ignore_roles) if ignore_roles else None,
            _dump_servers(required_servers),
        )

    async def set_giveaway_members(self, message_id: int, members: list[int]) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET members = $1::jsonb WHERE message_id = $2",
            json.dumps(members),
            message_id,
        )

    async def add_giveaway_member(self, message_id: int, user_id: int) -> list[int] | None:
        row = await self._pool.fetchrow(
            """
            UPDATE giveaways
            SET members = members || $1::jsonb
            WHERE message_id = $2
              AND NOT (members @> $1::jsonb)
            RETURNING members
            """,
            json.dumps([user_id]),
            message_id,
        )
        return _member_ids(row["members"]) if row else None

    async def remove_giveaway_member(self, message_id: int, user_id: int) -> list[int] | None:
        row = await self._pool.fetchrow(
            """
            UPDATE giveaways
            SET members = COALESCE((
                SELECT jsonb_agg(value)
                FROM jsonb_array_elements(members) AS value
                WHERE value <> to_jsonb($1::bigint)
            ), '[]'::jsonb)
            WHERE message_id = $2
            RETURNING members
            """,
            user_id,
            message_id,
        )
        return _member_ids(row["members"]) if row else None

    async def set_giveaway_title(self, message_id: int, title: str) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET title = $1 WHERE message_id = $2",
            title,
            message_id,
        )

    async def set_giveaway_finish(self, message_id: int, finish: datetime) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET finish = $1 WHERE message_id = $2",
            finish,
            message_id,
        )

    async def set_giveaway_host(self, message_id: int, host_id: int) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET host_id = $1 WHERE message_id = $2",
            host_id,
            message_id,
        )

    async def set_giveaway_winners(self, message_id: int, winners: int) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET winners = $1 WHERE message_id = $2",
            winners,
            message_id,
        )

    async def set_giveaway_roles(
        self,
        message_id: int,
        column: str,
        role_ids: list[int] | None,
    ) -> None:
        if column not in {"required_roles", "ignore_roles"}:
            raise ValueError(f"invalid giveaway column: {column}")
        await self._pool.execute(
            f"UPDATE giveaways SET {column} = $1::jsonb WHERE message_id = $2",
            json.dumps(role_ids) if role_ids else None,
            message_id,
        )

    async def set_giveaway_servers(
        self,
        message_id: int,
        servers: list[SponsoredServer] | None,
    ) -> None:
        await self._pool.execute(
            "UPDATE giveaways SET required_servers = $1::jsonb WHERE message_id = $2",
            _dump_servers(servers),
            message_id,
        )

    async def delete_giveaway(self, message_id: int) -> None:
        await self._pool.execute("DELETE FROM giveaways WHERE message_id = $1", message_id)

    async def ended_giveaway(self, channel_id: int, message_id: int) -> list[int] | None:
        row = await self._pool.fetchrow(
            """
            SELECT members FROM giveaways_ended
            WHERE channel_id = $1 AND message_id = $2
            """,
            channel_id,
            message_id,
        )
        return _member_ids(row["members"]) if row else None

    async def store_ended_giveaway(
        self,
        channel_id: int,
        message_id: int,
        members: list[int],
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO giveaways_ended (message_id, channel_id, members)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (message_id) DO UPDATE
            SET channel_id = EXCLUDED.channel_id, members = EXCLUDED.members
            """,
            message_id,
            channel_id,
            json.dumps(members),
        )
        await self.delete_giveaway(message_id)

    async def package(self, package_id: int) -> Package | None:
        row = await self._pool.fetchrow("SELECT * FROM packages WHERE id = $1", package_id)
        return _package(row) if row else None

    async def create_package(
        self,
        *,
        packager_id: int,
        package_type: str,
        title: str,
        price: int,
        description: str,
        sell_type: str,
        customizable: bool,
        storage_channel_id: int,
        storage_message_id: int,
        submission_channel_id: int,
        submission_message_id: int,
        showcase_filename: str,
    ) -> Package:
        row = await self._pool.fetchrow(
            """
            INSERT INTO packages (
                packager_id, package_type, title, price, description, sell_type,
                customizable, storage_channel_id, storage_message_id,
                submission_channel_id, submission_message_id, showcase_filename, status
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9,
                $10, $11, $12, 'pending'
            )
            RETURNING *
            """,
            packager_id,
            package_type,
            title,
            price,
            description,
            sell_type,
            customizable,
            storage_channel_id,
            storage_message_id,
            submission_channel_id,
            submission_message_id,
            showcase_filename,
        )
        return _package(row)

    async def set_package_submission(self, package_id: int, message_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE packages
            SET submission_message_id = $2, updated_at = NOW()
            WHERE id = $1
            """,
            package_id,
            message_id,
        )

    async def claim_package(self, package_id: int, reviewer_id: int) -> Package | None:
        row = await self._pool.fetchrow(
            """
            UPDATE packages
            SET status = 'processing', reviewer_id = $2, updated_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            package_id,
            reviewer_id,
        )
        return _package(row) if row else None

    async def revert_package_pending(self, package_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE packages
            SET status = 'pending', reviewer_id = NULL, updated_at = NOW()
            WHERE id = $1 AND status = 'processing'
            """,
            package_id,
        )

    async def accept_package(
        self,
        package_id: int,
        *,
        gamepass_id: int,
        forum_channel_id: int,
        forum_thread_id: int,
        forum_message_id: int,
    ) -> Package | None:
        row = await self._pool.fetchrow(
            """
            UPDATE packages
            SET status = 'accepted',
                gamepass_id = $2,
                forum_channel_id = $3,
                forum_thread_id = $4,
                forum_message_id = $5,
                updated_at = NOW()
            WHERE id = $1 AND status = 'processing'
            RETURNING *
            """,
            package_id,
            gamepass_id,
            forum_channel_id,
            forum_thread_id,
            forum_message_id,
        )
        return _package(row) if row else None

    async def deny_package(self, package_id: int, reviewer_id: int) -> Package | None:
        row = await self._pool.fetchrow(
            """
            UPDATE packages
            SET status = 'denied', reviewer_id = $2, updated_at = NOW()
            WHERE id = $1 AND status IN ('pending', 'processing')
            RETURNING *
            """,
            package_id,
            reviewer_id,
        )
        return _package(row) if row else None

    async def mark_package_sold(self, package_id: int) -> Package | None:
        row = await self._pool.fetchrow(
            """
            UPDATE packages
            SET status = 'sold', sold_at = NOW(), updated_at = NOW()
            WHERE id = $1 AND status = 'accepted'
            RETURNING *
            """,
            package_id,
        )
        return _package(row) if row else None

    async def create_purchase(
        self,
        *,
        package_id: int,
        buyer_id: int,
        buyer_roblox_id: int,
        recipient_id: int | None,
        kind: str,
        expires_at: datetime,
    ) -> PackagePurchase:
        row = await self._pool.fetchrow(
            """
            INSERT INTO package_purchases (
                package_id, buyer_id, buyer_roblox_id, recipient_id, kind, status, expires_at
            ) VALUES ($1, $2, $3, $4, $5, 'pending', $6)
            RETURNING *
            """,
            package_id,
            buyer_id,
            buyer_roblox_id,
            recipient_id,
            kind,
            expires_at,
        )
        return _purchase(row)

    async def purchase(self, purchase_id: int) -> PackagePurchase | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM package_purchases WHERE id = $1",
            purchase_id,
        )
        return _purchase(row) if row else None

    async def pending_purchases(self, now: datetime) -> list[PackagePurchase]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM package_purchases
            WHERE status = 'pending' AND expires_at > $1
            ORDER BY expires_at ASC
            """,
            now,
        )
        return [_purchase(row) for row in rows]

    async def expire_purchases(self, now: datetime) -> int:
        result = await self._pool.execute(
            """
            UPDATE package_purchases
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at <= $1
            """,
            now,
        )
        return int(str(result).rsplit(" ", maxsplit=1)[-1] or 0)

    async def mark_purchase_paid(
        self,
        purchase_id: int,
        *,
        packager_id: int,
        gross: int,
        packager_amount: int,
        network_amount: int,
    ) -> PackagePurchase | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE package_purchases
                    SET status = 'paid', paid_at = NOW()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    purchase_id,
                )
                if row is None:
                    return None
                await connection.execute(
                    """
                    INSERT INTO package_payouts (
                        purchase_id, packager_id, gross, packager_amount, network_amount, status
                    ) VALUES ($1, $2, $3, $4, $5, 'pending')
                    ON CONFLICT (purchase_id) DO NOTHING
                    """,
                    purchase_id,
                    packager_id,
                    gross,
                    packager_amount,
                    network_amount,
                )
                return _purchase(row)

    async def mark_purchase_undelivered(self, purchase_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE package_purchases
            SET status = 'undelivered'
            WHERE id = $1 AND status = 'paid'
            """,
            purchase_id,
        )

    async def mark_purchase_delivered(self, purchase_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE package_purchases
            SET status = 'paid', delivered_at = NOW()
            WHERE id = $1 AND status IN ('paid', 'undelivered')
            """,
            purchase_id,
        )

    async def buyer_owns_package(self, package_id: int, buyer_id: int) -> bool:
        value = await self._pool.fetchval(
            """
            SELECT 1 FROM package_purchases
            WHERE package_id = $1 AND buyer_id = $2
              AND status IN ('pending', 'paid', 'undelivered')
            LIMIT 1
            """,
            package_id,
            buyer_id,
        )
        return value is not None

    async def payout_summary(self) -> list[PackagerPayoutSummary]:
        rows = await self._pool.fetch(
            """
            SELECT packager_id,
                   COALESCE(SUM(packager_amount) FILTER (WHERE status = 'pending'), 0)::bigint
                     AS pending_total,
                   COALESCE(SUM(packager_amount) FILTER (WHERE status = 'paid'), 0)::bigint
                     AS paid_total,
                   COUNT(*) FILTER (WHERE status = 'pending')::bigint AS pending_count
            FROM package_payouts
            GROUP BY packager_id
            ORDER BY pending_total DESC
            """
        )
        return [
            PackagerPayoutSummary(
                packager_id=int(row["packager_id"]),
                pending_total=int(row["pending_total"]),
                paid_total=int(row["paid_total"]),
                pending_count=int(row["pending_count"]),
            )
            for row in rows
        ]

    async def payouts_for(self, packager_id: int) -> list[PackagePayout]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM package_payouts
            WHERE packager_id = $1
            ORDER BY created_at DESC
            """,
            packager_id,
        )
        return [_payout(row) for row in rows]

    async def packager_earnings_by_package(
        self,
        packager_id: int,
    ) -> list[PackagerPackageEarnings]:
        rows = await self._pool.fetch(
            """
            SELECT pkg.id AS package_id,
                   pkg.title,
                   pkg.forum_thread_id,
                   pkg.forum_message_id,
                   COUNT(*)::bigint AS sales,
                   COALESCE(SUM(pp.packager_amount), 0)::bigint AS earned,
                   COUNT(*) FILTER (WHERE pp.status = 'pending')::bigint AS pending_sales,
                   COALESCE(
                     SUM(pp.packager_amount) FILTER (WHERE pp.status = 'pending'), 0
                   )::bigint AS pending_total,
                   COALESCE(
                     SUM(pp.packager_amount) FILTER (WHERE pp.status = 'paid'), 0
                   )::bigint AS paid_total
            FROM package_payouts pp
            JOIN package_purchases pu ON pu.id = pp.purchase_id
            JOIN packages pkg ON pkg.id = pu.package_id
            WHERE pp.packager_id = $1
            GROUP BY pkg.id, pkg.title, pkg.forum_thread_id, pkg.forum_message_id
            ORDER BY pending_total DESC, earned DESC, pkg.title ASC
            """,
            packager_id,
        )
        return [
            PackagerPackageEarnings(
                package_id=int(row["package_id"]),
                title=str(row["title"]),
                forum_thread_id=(
                    int(row["forum_thread_id"]) if row["forum_thread_id"] is not None else None
                ),
                forum_message_id=(
                    int(row["forum_message_id"]) if row["forum_message_id"] is not None else None
                ),
                sales=int(row["sales"]),
                earned=int(row["earned"]),
                pending_sales=int(row["pending_sales"]),
                pending_total=int(row["pending_total"]),
                paid_total=int(row["paid_total"]),
            )
            for row in rows
        ]

    async def settle_payouts(self, packager_id: int, settled_by: int) -> int:
        result = await self._pool.execute(
            """
            UPDATE package_payouts
            SET status = 'paid', settled_by = $2, settled_at = NOW()
            WHERE packager_id = $1 AND status = 'pending'
            """,
            packager_id,
            settled_by,
        )
        return int(str(result).rsplit(" ", maxsplit=1)[-1] or 0)

    async def recent_report(self, package_id: int, reporter_id: int, since: datetime) -> bool:
        value = await self._pool.fetchval(
            """
            SELECT 1 FROM package_reports
            WHERE package_id = $1 AND reporter_id = $2 AND created_at >= $3
            LIMIT 1
            """,
            package_id,
            reporter_id,
            since,
        )
        return value is not None

    async def add_report(self, package_id: int, reporter_id: int, issue: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO package_reports (package_id, reporter_id, issue)
            VALUES ($1, $2, $3)
            """,
            package_id,
            reporter_id,
            issue,
        )

    async def sticky(self, channel_id: int) -> StickyMessage | None:
        row = await self._pool.fetchrow(
            """
            SELECT channel_id, guild_id, message, last_message_id, keep_old
            FROM sticky_messages
            WHERE channel_id = $1
            """,
            channel_id,
        )
        return _sticky(row) if row else None

    async def stickies(self, guild_id: int) -> list[StickyMessage]:
        rows = await self._pool.fetch(
            """
            SELECT channel_id, guild_id, message, last_message_id, keep_old
            FROM sticky_messages
            WHERE guild_id = $1
            ORDER BY channel_id ASC
            """,
            guild_id,
        )
        return [_sticky(row) for row in rows]

    async def upsert_sticky(
        self,
        guild_id: int,
        channel_id: int,
        message: str,
        keep_old: bool,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO sticky_messages (channel_id, guild_id, message, last_message_id, keep_old)
            VALUES ($1, $2, $3, NULL, $4)
            ON CONFLICT (channel_id) DO UPDATE
            SET guild_id = EXCLUDED.guild_id,
                message = EXCLUDED.message,
                keep_old = EXCLUDED.keep_old
            """,
            channel_id,
            guild_id,
            message,
            keep_old,
        )

    async def set_sticky_last_message(self, channel_id: int, message_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE sticky_messages
            SET last_message_id = $2
            WHERE channel_id = $1
            """,
            channel_id,
            message_id,
        )

    async def delete_sticky(self, channel_id: int) -> bool:
        result = await self._pool.execute(
            "DELETE FROM sticky_messages WHERE channel_id = $1",
            channel_id,
        )
        return str(result).endswith("1")

    async def guild_tag(self, guild_id: int) -> GuildTag | None:
        row = await self._pool.fetchrow(
            """
            SELECT guild_id, enabled, channel_id, message, role_ids
            FROM guild_tags
            WHERE guild_id = $1
            """,
            guild_id,
        )
        return _guild_tag(row) if row else None

    async def ensure_guild_tag(self, guild_id: int) -> GuildTag:
        await self._pool.execute(
            """
            INSERT INTO guild_tags (guild_id, enabled)
            VALUES ($1, FALSE)
            ON CONFLICT (guild_id) DO NOTHING
            """,
            guild_id,
        )
        row = await self.guild_tag(guild_id)
        if row is None:
            raise RuntimeError("guild tag row missing after ensure")
        return row

    async def set_guild_tag_enabled(self, guild_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_tags (guild_id, enabled)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            guild_id,
            enabled,
        )

    async def set_guild_tag_message(self, guild_id: int, message: str) -> None:
        await self._pool.execute(
            "UPDATE guild_tags SET message = $2 WHERE guild_id = $1",
            guild_id,
            message,
        )

    async def set_guild_tag_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self._pool.execute(
            "UPDATE guild_tags SET channel_id = $2 WHERE guild_id = $1",
            guild_id,
            channel_id,
        )

    async def set_guild_tag_roles(self, guild_id: int, role_ids: list[int]) -> None:
        await self._pool.execute(
            "UPDATE guild_tags SET role_ids = $2::jsonb WHERE guild_id = $1",
            guild_id,
            json.dumps(role_ids),
        )

    async def unclaimed_sales(
        self,
        group_id: int,
        agent_id: int,
        item_ids: list[int],
    ) -> list[Sale]:
        rows = await self._pool.fetch(
            """
            SELECT t.raw
            FROM transactions t
            LEFT JOIN promotion_claims c ON c.transaction_id = t.id
            WHERE t.group_id = $1
              AND t.kind = 'Sale'
              AND t.agent_id = $2
              AND t.item_id = ANY($3::bigint[])
              AND c.transaction_id IS NULL
            ORDER BY t.created_at ASC
            """,
            group_id,
            agent_id,
            item_ids,
        )
        return [sale for row in rows if (sale := _sale(row))]

    async def unclaimed_item_sales(
        self,
        group_id: int,
        item_ids: list[int],
        since: datetime,
    ) -> list[Sale]:
        rows = await self._pool.fetch(
            """
            SELECT t.raw
            FROM transactions t
            LEFT JOIN promotion_claims c ON c.transaction_id = t.id
            WHERE t.group_id = $1
              AND t.kind = 'Sale'
              AND t.item_id = ANY($2::bigint[])
              AND t.created_at >= $3
              AND c.transaction_id IS NULL
            ORDER BY t.created_at ASC
            """,
            group_id,
            item_ids,
            since,
        )
        return [sale for row in rows if (sale := _sale(row))]

    async def claim_promotion(
        self,
        transaction_id: int,
        item_id: int,
        kind: str,
        owner_id: int,
        roblox_id: int,
    ) -> Promotion | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                claimed = await connection.fetchval(
                    """
                    INSERT INTO promotion_claims (transaction_id, item_id, owner_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (transaction_id) DO NOTHING
                    RETURNING transaction_id
                    """,
                    transaction_id,
                    item_id,
                    owner_id,
                )
                if claimed is None:
                    return None
                row = await connection.fetchrow(
                    """
                    INSERT INTO promotions (kind, owner_id, roblox_id, transaction_id)
                    VALUES ($1, $2, $3, $4)
                    RETURNING *
                    """,
                    kind,
                    owner_id,
                    roblox_id,
                    transaction_id,
                )
                await connection.execute(
                    "UPDATE promotion_claims SET promotion_id = $1 WHERE transaction_id = $2",
                    row["id"],
                    transaction_id,
                )
                return _promotion(row)

    async def claim_upgrade(
        self,
        transaction_id: int,
        item_id: int,
        owner_id: int,
        promotion_id: int,
        tier: str,
        slot: date | None,
    ) -> Promotion | None:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    claimed = await connection.fetchval(
                        """
                        INSERT INTO promotion_claims (
                            transaction_id, item_id, owner_id, promotion_id
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (transaction_id) DO NOTHING
                        RETURNING transaction_id
                        """,
                        transaction_id,
                        item_id,
                        owner_id,
                        promotion_id,
                    )
                    if claimed is None:
                        return None
                    row = await connection.fetchrow(
                        """
                        UPDATE promotions
                        SET tier = $2,
                            slot = COALESCE($3::date, slot),
                            alerted = CASE WHEN $3::date IS NULL THEN alerted ELSE FALSE END
                        WHERE id = $1
                          AND owner_id = $4
                          AND status IN ('claimed', 'submitted', 'approved')
                        RETURNING *
                        """,
                        promotion_id,
                        tier,
                        slot,
                        owner_id,
                    )
                    if row is None:
                        raise _Rollback()
                    return _promotion(row)
        except _Rollback:
            return None

    async def promotion(self, promotion_id: int) -> Promotion | None:
        row = await self._pool.fetchrow("SELECT * FROM promotions WHERE id = $1", promotion_id)
        return _promotion(row) if row else None

    async def promotion_by_ticket(self, channel_id: int) -> Promotion | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM promotions WHERE ticket_channel_id = $1",
            channel_id,
        )
        return _promotion(row) if row else None

    async def active_promotion(self, owner_id: int) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            SELECT * FROM promotions
            WHERE owner_id = $1 AND status IN ('claimed', 'submitted', 'approved')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            owner_id,
        )
        return _promotion(row) if row else None

    async def unsubmitted_promotions(self, owner_id: int) -> list[Promotion]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM promotions
            WHERE owner_id = $1 AND status IN ('claimed', 'denied')
            ORDER BY created_at ASC
            """,
            owner_id,
        )
        return [_promotion(row) for row in rows]

    async def submit_promotion(
        self,
        promotion_id: int,
        owner_id: int,
        data: dict[str, Any],
    ) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET data = $3::jsonb, status = 'submitted'
            WHERE id = $1 AND owner_id = $2 AND status IN ('claimed', 'denied')
            RETURNING *
            """,
            promotion_id,
            owner_id,
            json.dumps(data),
        )
        return _promotion(row) if row else None

    async def edit_promotion(self, promotion_id: int, data: dict[str, Any]) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET data = $2::jsonb
            WHERE id = $1 AND status IN ('submitted', 'approved')
            RETURNING *
            """,
            promotion_id,
            json.dumps(data),
        )
        return _promotion(row) if row else None

    async def approve_promotion(
        self,
        promotion_id: int,
        slot: date,
        reviewer_id: int,
    ) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET status = 'approved', slot = $2, reviewer_id = $3,
                approved_at = NOW(), alerted = FALSE
            WHERE id = $1 AND status = 'submitted'
            RETURNING *
            """,
            promotion_id,
            slot,
            reviewer_id,
        )
        return _promotion(row) if row else None

    async def deny_promotion(self, promotion_id: int, reviewer_id: int) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET status = 'denied', reviewer_id = $2
            WHERE id = $1 AND status = 'submitted'
            RETURNING *
            """,
            promotion_id,
            reviewer_id,
        )
        return _promotion(row) if row else None

    async def set_promotion_slot(self, promotion_id: int, slot: date) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET slot = $2, alerted = FALSE
            WHERE id = $1 AND status = 'approved'
            RETURNING *
            """,
            promotion_id,
            slot,
        )
        return _promotion(row) if row else None

    async def shift_promotion_slots(
        self,
        start: date,
        days: int,
        exclude_id: int,
    ) -> list[Promotion]:
        rows = await self._pool.fetch(
            """
            UPDATE promotions
            SET slot = slot + $2::int, alerted = FALSE
            WHERE status = 'approved' AND tier = 'normal' AND slot >= $1 AND id <> $3
            RETURNING *
            """,
            start,
            days,
            exclude_id,
        )
        return [_promotion(row) for row in rows]

    async def set_promotion_log(self, promotion_id: int, message_id: int) -> None:
        await self._pool.execute(
            "UPDATE promotions SET log_message_id = $2 WHERE id = $1",
            promotion_id,
            message_id,
        )

    async def set_promotion_ticket(self, promotion_id: int, channel_id: int) -> None:
        await self._pool.execute(
            "UPDATE promotions SET ticket_channel_id = $2 WHERE id = $1",
            promotion_id,
            channel_id,
        )

    async def due_promotions(self, today: date) -> list[Promotion]:
        rows = await self._pool.fetch(
            """
            UPDATE promotions
            SET alerted = TRUE
            WHERE status = 'approved' AND slot <= $1 AND NOT alerted
            RETURNING *
            """,
            today,
        )
        return [_promotion(row) for row in rows]

    async def mark_promotion_posted(self, promotion_id: int, url: str) -> Promotion | None:
        row = await self._pool.fetchrow(
            """
            UPDATE promotions
            SET status = 'posted', post_url = $2
            WHERE id = $1 AND status = 'approved'
            RETURNING *
            """,
            promotion_id,
            url,
        )
        return _promotion(row) if row else None

    async def queued_promotions(self) -> list[Promotion]:
        rows = await self._pool.fetch(
            "SELECT * FROM promotions WHERE status = 'approved' ORDER BY slot ASC, id ASC"
        )
        return [_promotion(row) for row in rows]

    async def last_promotion_slot(self) -> date | None:
        value = await self._pool.fetchval(
            "SELECT MAX(slot) FROM promotions WHERE status = 'approved'"
        )
        return value if isinstance(value, date) else None


def _sticky(row: Any) -> StickyMessage:
    return StickyMessage(
        channel_id=int(row["channel_id"]),
        guild_id=int(row["guild_id"]),
        message=str(row["message"]),
        last_message_id=(
            int(row["last_message_id"]) if row["last_message_id"] is not None else None
        ),
        keep_old=bool(row["keep_old"]),
    )


def _guild_tag(row: Any) -> GuildTag:
    return GuildTag(
        guild_id=int(row["guild_id"]),
        enabled=bool(row["enabled"]),
        channel_id=int(row["channel_id"]) if row["channel_id"] is not None else None,
        message=str(row["message"] or ""),
        role_ids=_ids(row["role_ids"]) or [],
    )


async def connect(dsn: str) -> tuple[Database, str]:
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,
    )
    if pool is None:
        raise RuntimeError("Failed to connect to the database")
    for statement in _SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await pool.execute(sql)
    version = await pool.fetchval("SELECT version()")
    return Database(pool), str(version).split("(", maxsplit=1)[0].strip()
