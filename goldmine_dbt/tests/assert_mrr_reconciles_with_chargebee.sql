-- Reconciliation. This month's closing MRR, rebuilt from the events log, must equal the MRR of the
-- subscriptions as Chargebee holds them right now. If Finance says the dashboard does not match
-- Chargebee, this is the first thing to look at.
with model as (
    select closing_mrr_cents
    from {{ ref('fct_saas_metrics_monthly') }}
    where month_start = cast({{ dbt.date_trunc('month', 'current_date') }} as date)
),

chargebee as (
    select sum(mrr_cents) as current_mrr_cents
    from {{ ref('int_subscriptions__enriched') }}
    where not is_test_account
)

select model.closing_mrr_cents, chargebee.current_mrr_cents
from model
cross join chargebee
where model.closing_mrr_cents != chargebee.current_mrr_cents
