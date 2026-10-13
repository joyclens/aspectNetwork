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
