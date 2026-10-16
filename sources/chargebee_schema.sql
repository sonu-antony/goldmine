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
            'paused',
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
-- A credit note is money given back against a subscription: a downgrade credit or a refund.
CREATE TABLE IF NOT EXISTS chargebee.credit_note (
    id BIGINT PRIMARY KEY,
    subscription_id BIGINT NOT NULL,
    amount_cents INTEGER NOT NULL,
    reason TEXT NOT NULL CHECK (
        reason IN (
            'order_change',
            'service_unsatisfactory'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'adjusted',
            'refunded',
            'voided'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_subscription FOREIGN KEY (subscription_id) REFERENCES chargebee.subscription (id)
);

-- Chargebee keeps an events log: every change to a subscription, with the state after the change.
CREATE TABLE IF NOT EXISTS chargebee.subscription_event (
    id BIGINT PRIMARY KEY,
    subscription_id BIGINT NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'subscription_created',
            'subscription_activated',
            'subscription_changed',
            'subscription_paused',
            'subscription_resumed',
            'subscription_cancellation_scheduled',
            'subscription_cancelled',
            'subscription_reactivated'
        )
    ),
    occurred_at TIMESTAMPTZ NOT NULL,
    plan_id BIGINT NOT NULL,
    plan_amount_cents INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_subscription FOREIGN KEY (subscription_id) REFERENCES chargebee.subscription (id)
);
