select
    id as customer_id,
    name as customer_name,
    workspace_id,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('chargebee', 'chargebee_customer')) }} as customer
