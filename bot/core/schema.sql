CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT PRIMARY KEY,
    group_id BIGINT NOT NULL,
    kind TEXT NOT NULL,
    amount BIGINT NOT NULL,
    currency TEXT NOT NULL,
    agent_id BIGINT,
    agent_name TEXT,
    agent_type TEXT,
    item_id BIGINT,
    item_name TEXT,
    item_type TEXT,
    pending BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    raw JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS transactions_group_kind_created_idx
    ON transactions (group_id, kind, created_at DESC);

CREATE INDEX IF NOT EXISTS transactions_group_agent_created_idx
    ON transactions (group_id, agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS transactions_group_amount_idx
    ON transactions (group_id, amount DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    channel_id BIGINT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    claimed_by BIGINT,
    number INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'general',
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS tickets_owner_idx
    ON tickets (owner_id);

CREATE SEQUENCE IF NOT EXISTS ticket_number_seq START 1;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'general';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS ticket_claims (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ticket_claims_user_idx
    ON ticket_claims (user_id);

CREATE TABLE IF NOT EXISTS giveaways (
    message_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    winners INTEGER NOT NULL,
    members JSONB NOT NULL DEFAULT '[]'::jsonb,
    finish TIMESTAMPTZ NOT NULL,
    host_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    required_roles JSONB,
    bonus_roles JSONB,
    ignore_roles JSONB,
    required_servers JSONB
);

CREATE INDEX IF NOT EXISTS giveaways_guild_idx
    ON giveaways (guild_id);

CREATE INDEX IF NOT EXISTS giveaways_finish_idx
    ON giveaways (finish);

CREATE TABLE IF NOT EXISTS giveaways_ended (
    message_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    members JSONB NOT NULL
);
