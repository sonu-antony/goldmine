CREATE SCHEMA IF NOT EXISTS chargebee;

CREATE TABLE IF NOT EXISTS chargebee.customer (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    workspace_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chargebee.plan (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    monthly_price_cents INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chargebee.subscription (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    plan_id BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'active',
            'cancelled',
            'non_renewing',
            'in_trial',
            'future'
        )
    ),
    plan_amount_cents INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    start_date DATE NOT NULL,
    cancelled_date DATE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_plan FOREIGN KEY (plan_id) REFERENCES chargebee.plan (id),
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES chargebee.customer (id)
);

CREATE TABLE IF NOT EXISTS chargebee.invoice (
    id BIGINT PRIMARY KEY,
    subscription_id BIGINT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'paid',
            'payment_due',
            'voided'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_subscription FOREIGN KEY (subscription_id) REFERENCES chargebee.subscription (id)
);