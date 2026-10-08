CREATE SCHEMA IF NOT EXISTS hubspot;

-- chargebee_customer_id is a plain value, not a foreign key: different system
CREATE TABLE IF NOT EXISTS hubspot.companies (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT,
    chargebee_customer_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS hubspot.deals (
    id BIGINT PRIMARY KEY,
    company_id BIGINT NOT NULL,
    stage TEXT NOT NULL CHECK (
        stage IN (
            'appointment_scheduled',
            'qualified_to_buy',
            'contract_sent',
            'closed_won',
            'closed_lost'
        )
    ),
    amount_cents INTEGER NOT NULL,
    close_date DATE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES hubspot.companies (id)
);
