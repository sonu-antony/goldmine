{{ config(dist='all', sort=['workspace_id']) }}
{# Grain: one row per workspace, with its billing state and recent activity. #}
with activity as (
    select
        workspace_id,
        min(activity_date) as first_activity_date,
        max(activity_date) as last_activity_date,
        sum(case when activity_date >= current_date - 28 then messages_sent else 0 end) as messages_sent_last_28_days
    from {{ ref('fct_workspace_activity_daily') }}
    group by workspace_id
)

select
    workspaces.workspace_id,
    workspaces.workspace_name,
    workspaces.is_internal_account,
    workspaces.user_count,
    workspaces.created_at,
    customers.customer_id,
    customers.current_plan,
    customers.current_status,
    coalesce(customers.current_mrr_cents, 0) as current_mrr_cents,
    activity.first_activity_date,
    activity.last_activity_date,
    coalesce(activity.messages_sent_last_28_days, 0) as messages_sent_last_28_days,
    (coalesce(activity.messages_sent_last_28_days, 0) >= {{ var('active_workspace_min_outbound_messages') }}) as is_active_last_28_days
from {{ ref('int_workspaces') }} as workspaces
left join {{ ref('dim_customers') }} as customers on customers.customer_id = workspaces.customer_id
left join activity on activity.workspace_id = workspaces.workspace_id
