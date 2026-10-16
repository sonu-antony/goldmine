{# Grain: one row per subscription, with its plan and its resolved customer.
   Monthly recurring revenue rule: a subscription counts while it is active or non_renewing
   (cancelled but still inside the paid period). Paused, trial, future and cancelled count as zero. #}
select
    subscriptions.subscription_id,
    subscriptions.customer_id,
    customers.workspace_id,
    customers.is_test_account,
    plans.plan_name,
    subscriptions.subscription_status,
    subscriptions.plan_amount_cents,
    subscriptions.quantity,
    case
        when subscriptions.subscription_status in ('active', 'non_renewing')
            then subscriptions.plan_amount_cents * subscriptions.quantity
        else 0
    end as mrr_cents,
    subscriptions.started_on,
    subscriptions.cancelled_on
from {{ ref('stg_chargebee__subscription') }} as subscriptions
inner join {{ ref('int_customers__resolved') }} as customers on customers.customer_id = subscriptions.customer_id
left join {{ ref('stg_chargebee__plan') }} as plans on plans.plan_id = subscriptions.plan_id
