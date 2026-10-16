-- The events log must agree with the current subscription row. If it does not, history built from
-- events cannot be trusted. This must never fail.
with last_event as (
    select *
    from (
        select
            event.*,
            row_number() over (partition by subscription_id order by occurred_at desc, event_id desc) as event_rank
        from {{ ref('stg_chargebee__subscription_event') }} as event
    ) as ranked
    where event_rank = 1
)
select subscription.subscription_id
from {{ ref('stg_chargebee__subscription') }} as subscription
left join last_event on last_event.subscription_id = subscription.subscription_id
where last_event.subscription_id is null
   or last_event.plan_id != subscription.plan_id
   or last_event.plan_amount_cents != subscription.plan_amount_cents
   or last_event.quantity != subscription.quantity
   or last_event.subscription_status != subscription.subscription_status
