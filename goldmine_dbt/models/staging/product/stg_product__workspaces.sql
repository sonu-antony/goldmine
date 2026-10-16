select
    id as workspace_id,
    name as workspace_name,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('product', 'product_workspaces')) }} as workspace
