select
    id as credit_note_id,
    subscription_id,
    amount_cents,
    reason,
    status as credit_note_status,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_credit_note')) }} as credit_note
