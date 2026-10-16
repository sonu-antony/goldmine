{{ config(dist='customer_id', sort=['month_start']) }}
{# Grain: one row per customer per month in which they have, or had in the month before, any revenue.
   movement_type explains how MRR changed from last month:
     new          first month with revenue
     expansion    more revenue than last month (upgrade or more seats)
     contraction  less revenue, but still a customer
     churned      revenue went to zero because the subscription was cancelled
     paused       revenue went to zero because the subscription was paused (not churn)
     resumed      revenue came back after a pause
     reactivated  revenue came back after a cancellation
     unchanged    same revenue
   Amount columns are positive magnitudes. Bridge: closing = opening + new + expansion - contraction
   - churned + reactivated - paused + resumed. #}
with monthly as (
    select
        customer_id,
        month_start,
        mrr_cents,
        status_in_month,
        coalesce(lag(mrr_cents) over (partition by customer_id order by month_start), 0) as previous_mrr_cents,
        lag(status_in_month) over (partition by customer_id order by month_start) as previous_status,
        max(mrr_cents) over (
            partition by customer_id order by month_start rows between unbounded preceding and 1 preceding
        ) as best_earlier_mrr_cents
    from {{ ref('fct_mrr_monthly') }}
),

classified as (
    select
        *,
        case
            when previous_mrr_cents = 0 and mrr_cents > 0 and coalesce(best_earlier_mrr_cents, 0) = 0 then 'new'
            when previous_mrr_cents = 0 and mrr_cents > 0 and previous_status = 'paused' then 'resumed'
            when previous_mrr_cents = 0 and mrr_cents > 0 then 'reactivated'
            when previous_mrr_cents > 0 and mrr_cents = 0 and status_in_month = 'paused' then 'paused'
            when previous_mrr_cents > 0 and mrr_cents = 0 then 'churned'
            when mrr_cents > previous_mrr_cents then 'expansion'
            when mrr_cents < previous_mrr_cents then 'contraction'
            when mrr_cents > 0 then 'unchanged'
            else 'inactive'
        end as movement_type
    from monthly
)

select
    customer_id,
    month_start,
    movement_type,
    previous_mrr_cents,
    mrr_cents,
    case when movement_type = 'new' then mrr_cents else 0 end as new_mrr_cents,
    case when movement_type = 'expansion' then mrr_cents - previous_mrr_cents else 0 end as expansion_mrr_cents,
    case when movement_type = 'contraction' then previous_mrr_cents - mrr_cents else 0 end as contraction_mrr_cents,
    case when movement_type = 'churned' then previous_mrr_cents else 0 end as churned_mrr_cents,
    case when movement_type = 'reactivated' then mrr_cents else 0 end as reactivated_mrr_cents,
    case when movement_type = 'paused' then 0 else 0 end as paused_mrr_cents,
    case when movement_type = 'resumed' then mrr_cents else 0 end as resumed_mrr_cents
from classified
where movement_type != 'inactive'
