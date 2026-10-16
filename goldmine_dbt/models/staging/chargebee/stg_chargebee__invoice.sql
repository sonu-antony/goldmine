select
    id as invoice_id,
    subscription_id,
    amount_cents,
    status as invoice_status,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_invoice')) }} as invoice
