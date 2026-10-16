select
    id as event_id,
    subscription_id,
    event_type,
    occurred_at,
    plan_id,
    plan_amount_cents,
    quantity,
    status as subscription_status,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_subscription_event')) }} as subscription_event
