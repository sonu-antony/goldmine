select
    id as subscription_id,
    customer_id,
    plan_id,
    status as subscription_status,
    plan_amount_cents,
    quantity,
    start_date as started_on,
    cancelled_date as cancelled_on,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_subscription')) }} as subscription
