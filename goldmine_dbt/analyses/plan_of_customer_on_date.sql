{# Which plan was this customer on at a given date? Answered from the events log, which reaches back
   to the beginning, so it works for dates before the snapshot existed.
   Compile with:  dbt compile --select plan_of_customer_on_date --vars '{customer_id: 1050, as_of_date: "2026-03-15"}'
   and run the compiled SQL in psql. #}
with customer_subscriptions as (
    select subscription_id
    from {{ ref('stg_chargebee__subscription') }}
    where customer_id = {{ var('customer_id', 1050) }}
),

last_event_before_date as (
    select
        events.*,
        row_number() over (partition by events.subscription_id order by events.occurred_at desc, events.event_id desc) as event_rank
    from {{ ref('stg_chargebee__subscription_event') }} as events
    inner join customer_subscriptions on customer_subscriptions.subscription_id = events.subscription_id
    where events.occurred_at < cast('{{ var('as_of_date', '2026-03-15') }}' as date) + 1
)

select
    last_event_before_date.subscription_id,
    plans.plan_name,
    last_event_before_date.subscription_status,
    last_event_before_date.plan_amount_cents,
    last_event_before_date.quantity,
    last_event_before_date.occurred_at as state_since
from last_event_before_date
left join {{ ref('stg_chargebee__plan') }} as plans on plans.plan_id = last_event_before_date.plan_id
where event_rank = 1
