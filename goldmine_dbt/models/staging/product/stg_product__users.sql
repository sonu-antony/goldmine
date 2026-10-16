select
    id as user_id,
    workspace_id,
    lower(trim(email)) as email,
    role as user_role,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('product', 'product_users')) }} as app_user
