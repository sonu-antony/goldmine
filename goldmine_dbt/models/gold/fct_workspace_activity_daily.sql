{{
    config(
        materialized='incremental',
        unique_key=['workspace_id', 'activity_date'],
        incremental_strategy='delete+insert',
        dist='workspace_id',
        sort=['activity_date']
    )
}}
{# Grain: one row per workspace per day on which it sent or received a message.
   Incremental. Late-arriving messages (sent days ago, delivered to us today) are caught by
   looking at when messages ARRIVED (created_at), not when they were sent. Every (workspace, day)
   touched by a recent arrival is recomputed from all its messages, so a late row corrects its day.
   Arrivals from the last activity_lookback_days are re-read each run, which also covers late commits.
   A full refresh rebuilds everything.
   Quality rule: a message cannot be sent after it arrived. Rows that break it come from a server with
   a wrong clock and are excluded, so they cannot create activity on days that have not happened yet. #}
with changed_days as (
    select distinct workspace_id, sent_date as activity_date
    from {{ ref('stg_product__messages') }}
    where sent_at <= created_at
    {% if is_incremental() %}
      and created_at >= (
        select {{ dbt.dateadd('day', -var('activity_lookback_days'), 'max(last_message_arrived_at)') }}
        from {{ this }}
    )
    {% endif %}
)

select
    messages.workspace_id,
    messages.sent_date as activity_date,
    sum(case when messages.direction = 'outbound' then 1 else 0 end) as messages_sent,
    sum(case when messages.direction = 'inbound' then 1 else 0 end) as messages_received,
    count(distinct messages.user_id) as active_users,
    max(messages.created_at) as last_message_arrived_at
from {{ ref('stg_product__messages') }} as messages
inner join changed_days
    on changed_days.workspace_id = messages.workspace_id
    and changed_days.activity_date = messages.sent_date
where messages.sent_at <= messages.created_at
group by messages.workspace_id, messages.sent_date
