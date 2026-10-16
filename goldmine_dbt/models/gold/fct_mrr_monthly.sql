{{ config(dist='customer_id', sort=['month_start']) }}
{# Grain: one row per customer per month, from the month of their first subscription.
   mrr_cents is monthly recurring revenue at the end of the month, in cents. Test accounts are excluded.
   Redshift: distributed on customer_id so the lag window in fct_mrr_movements stays on one node,
   sorted on month_start so month filters skip blocks. #}
select
    subscriptions.customer_id,
    states.month_start,
    sum(states.mrr_cents) as mrr_cents,
    count(*) as subscriptions,
    sum(case when states.subscription_status in ('active', 'non_renewing') then 1 else 0 end) as active_subscriptions,
    sum(case when states.subscription_status = 'paused' then 1 else 0 end) as paused_subscriptions,
    sum(case when states.subscription_status in ('in_trial', 'future') then 1 else 0 end) as trial_subscriptions,
    case
        when sum(case when states.subscription_status in ('active', 'non_renewing') then 1 else 0 end) > 0 then 'active'
        when sum(case when states.subscription_status = 'paused' then 1 else 0 end) > 0 then 'paused'
        when sum(case when states.subscription_status in ('in_trial', 'future') then 1 else 0 end) > 0 then 'trial'
        else 'cancelled'
    end as status_in_month
from {{ ref('int_subscription_state_monthly') }} as states
inner join {{ ref('int_subscriptions__enriched') }} as subscriptions on subscriptions.subscription_id = states.subscription_id
where not subscriptions.is_test_account
group by subscriptions.customer_id, states.month_start
