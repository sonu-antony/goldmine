{# Grain: one row per subscription per month, from the month it started.
   The state is rebuilt from the events log: the last event before the end of the month. The
   current month is measured up to now. This is how history is recovered for months before the
   subscription snapshot existed. #}
with subscription_months as (
    select
        subscriptions.subscription_id,
        months.month_start,
        least(cast(months.next_month_start as timestamptz), current_timestamp) as as_of_at
    from {{ ref('stg_chargebee__subscription') }} as subscriptions
    inner join {{ ref('int_months') }} as months on months.next_month_start > subscriptions.started_on
),

ranked as (
    select
        subscription_months.subscription_id,
        subscription_months.month_start,
        events.plan_id,
        events.plan_amount_cents,
        events.quantity,
        events.subscription_status,
        row_number() over (
            partition by subscription_months.subscription_id, subscription_months.month_start
            order by events.occurred_at desc, events.event_id desc
        ) as event_rank
    from subscription_months
    inner join {{ ref('stg_chargebee__subscription_event') }} as events
        on events.subscription_id = subscription_months.subscription_id
        and events.occurred_at < subscription_months.as_of_at
)

select
    subscription_id,
    month_start,
    plan_id,
    plan_amount_cents,
    quantity,
    subscription_status,
    case
        when subscription_status in ('active', 'non_renewing') then plan_amount_cents * quantity
        else 0
    end as mrr_cents
from ranked
where event_rank = 1
