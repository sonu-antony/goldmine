select
    id as company_id,
    name as company_name,
    lower(regexp_replace(trim(domain), '^(https?://)?(www\.)?', '')) as domain,
    chargebee_customer_id,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('hubspot', 'hubspot_companies')) }} as company
