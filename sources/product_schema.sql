CREATE SCHEMA IF NOT EXISTS product;

CREATE TABLE IF NOT EXISTS product.workspaces (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS product.users (
    id BIGINT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'agent')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_workspace FOREIGN KEY (workspace_id) REFERENCES product.workspaces (id)
);

-- user_id is null for inbound messages (a customer wrote in, no agent involved)
CREATE TABLE IF NOT EXISTS product.messages (
    id BIGINT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT,
    channel TEXT NOT NULL CHECK (
        channel IN ('whatsapp', 'instagram', 'facebook', 'telegram', 'sms', 'email')
    ),
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    sent_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_workspace FOREIGN KEY (workspace_id) REFERENCES product.workspaces (id),
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES product.users (id)
);
