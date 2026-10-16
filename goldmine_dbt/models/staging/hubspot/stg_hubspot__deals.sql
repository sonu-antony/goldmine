select
    id as deal_id,
    company_id,
    stage as deal_stage,
    amount_cents,
    close_date as closed_on,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('hubspot', 'hubspot_deals')) }} as deal
