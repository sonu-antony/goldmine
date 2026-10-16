{# Grain: one row per calendar month, from the month of the first subscription to the current month.
   A recursive query instead of generate_series, which Redshift only allows on the leader node. #}
with recursive first_subscription as (
    select cast({{ dbt.date_trunc('month', 'min(started_on)') }} as date) as first_month
    from {{ ref('stg_chargebee__subscription') }}
),

months as (
    select first_month as month_start
    from first_subscription

    union all

    select cast({{ dbt.dateadd('month', 1, 'month_start') }} as date)
    from months
    where month_start < cast({{ dbt.date_trunc('month', 'current_date') }} as date)
)

select
    month_start,
    cast({{ dbt.dateadd('month', 1, 'month_start') }} as date) as next_month_start
from months
