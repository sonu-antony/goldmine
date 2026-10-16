-- Each month must balance: closing = opening + new + expansion - contraction - churned + reactivated
-- - paused + resumed. And each month's opening must equal the previous month's closing.
with metrics as (
    select
        *,
        lag(closing_mrr_cents) over (order by month_start) as previous_closing_mrr_cents
    from {{ ref('fct_saas_metrics_monthly') }}
)

select month_start
from metrics
where closing_mrr_cents != opening_mrr_cents + new_mrr_cents + expansion_mrr_cents - contraction_mrr_cents
                           - churned_mrr_cents + reactivated_mrr_cents - paused_mrr_cents + resumed_mrr_cents
   or (previous_closing_mrr_cents is not null and opening_mrr_cents != previous_closing_mrr_cents)
