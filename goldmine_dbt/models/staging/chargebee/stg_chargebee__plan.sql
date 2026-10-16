select
    id as plan_id,
    name as plan_name,
    monthly_price_cents,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_plan')) }} as plan
