{{ config(dist='all', sort=['month_start']) }}
{# Grain: one row per month. Active workspace definition, agreed once and modelled once:
   a workspace is active in a month if it sent at least `active_workspace_min_outbound_messages`
   outbound messages in that calendar month. Internal test accounts are excluded.
   The current month is partial (month to date). #}
with monthly_activity as (
    select
        activity.workspace_id,
        cast({{ dbt.date_trunc('month', 'activity.activity_date') }} as date) as month_start,
        sum(activity.messages_sent) as messages_sent
    from {{ ref('fct_workspace_activity_daily') }} as activity
    inner join {{ ref('int_workspaces') }} as workspaces on workspaces.workspace_id = activity.workspace_id
    where not workspaces.is_internal_account
    group by activity.workspace_id, cast({{ dbt.date_trunc('month', 'activity.activity_date') }} as date)
),

workspace_counts as (
    select
        months.month_start,
        count(workspaces.workspace_id) as workspaces_created
    from {{ ref('int_months') }} as months
    left join {{ ref('int_workspaces') }} as workspaces
        on workspaces.created_at < cast(months.next_month_start as timestamptz)
        and not workspaces.is_internal_account
    group by months.month_start
)

select
    workspace_counts.month_start,
    workspace_counts.workspaces_created,
    sum(case when monthly_activity.messages_sent >= {{ var('active_workspace_min_outbound_messages') }} then 1 else 0 end) as active_workspaces,
    cast(sum(case when monthly_activity.messages_sent >= {{ var('active_workspace_min_outbound_messages') }} then 1 else 0 end) as decimal(18, 6))
        / nullif(workspace_counts.workspaces_created, 0) as active_workspace_rate,
    (workspace_counts.month_start = cast({{ dbt.date_trunc('month', 'current_date') }} as date)) as is_current_month
from workspace_counts
left join monthly_activity on monthly_activity.month_start = workspace_counts.month_start
group by workspace_counts.month_start, workspace_counts.workspaces_created
