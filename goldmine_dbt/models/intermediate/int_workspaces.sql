{# Grain: one row per workspace. Adds the internal-account flag and the user count. #}
with users as (
    select workspace_id, count(*) as user_count
    from {{ ref('stg_product__users') }}
    group by workspace_id
)

select
    workspaces.workspace_id,
    workspaces.workspace_name,
    (workspaces.workspace_name like 'Acme QA%' or workspaces.workspace_name like 'zz\_loadtest%') as is_internal_account,
    coalesce(users.user_count, 0) as user_count,
    customers.customer_id,
    workspaces.created_at,
    workspaces.updated_at
from {{ ref('stg_product__workspaces') }} as workspaces
left join users on users.workspace_id = workspaces.workspace_id
left join {{ ref('int_customers__resolved') }} as customers on customers.workspace_id = workspaces.workspace_id
