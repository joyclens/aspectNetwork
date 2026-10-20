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

CREATE TABLE IF NOT EXISTS packages (
    id BIGSERIAL PRIMARY KEY,
    packager_id BIGINT NOT NULL,
    package_type TEXT NOT NULL,
    title TEXT NOT NULL,
    price BIGINT NOT NULL,
    description TEXT NOT NULL,
    sell_type TEXT NOT NULL,
    customizable BOOLEAN NOT NULL,
    storage_channel_id BIGINT,
    storage_message_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id BIGINT,
    gamepass_id BIGINT,
    forum_channel_id BIGINT,
    forum_thread_id BIGINT,
    forum_message_id BIGINT,
    submission_channel_id BIGINT,
    submission_message_id BIGINT,
    showcase_filename TEXT NOT NULL DEFAULT '',
    sold_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS packages_status_idx ON packages (status);
CREATE INDEX IF NOT EXISTS packages_packager_idx ON packages (packager_id);

CREATE TABLE IF NOT EXISTS package_purchases (
    id BIGSERIAL PRIMARY KEY,
    package_id BIGINT NOT NULL REFERENCES packages (id),
    buyer_id BIGINT NOT NULL,
    buyer_roblox_id BIGINT NOT NULL,
    recipient_id BIGINT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS package_purchases_status_expires_idx
    ON package_purchases (status, expires_at);

CREATE TABLE IF NOT EXISTS package_payouts (
    id BIGSERIAL PRIMARY KEY,
    purchase_id BIGINT NOT NULL UNIQUE REFERENCES package_purchases (id),
    packager_id BIGINT NOT NULL,
    gross BIGINT NOT NULL,
    packager_amount BIGINT NOT NULL,
    network_amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    settled_by BIGINT,
    settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS package_payouts_packager_status_idx
    ON package_payouts (packager_id, status);

CREATE TABLE IF NOT EXISTS package_reports (
    id BIGSERIAL PRIMARY KEY,
    package_id BIGINT NOT NULL REFERENCES packages (id),
    reporter_id BIGINT NOT NULL,
    issue TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS package_reports_cooldown_idx
    ON package_reports (package_id, reporter_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sticky_messages (
    channel_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    last_message_id BIGINT,
    keep_old BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS sticky_messages_guild_idx
    ON sticky_messages (guild_id);

CREATE TABLE IF NOT EXISTS guild_tags (
    guild_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    channel_id BIGINT,
    message TEXT NOT NULL DEFAULT '',
    role_ids JSONB NOT NULL DEFAULT '[]'::jsonb
);
