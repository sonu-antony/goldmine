{{ config(dist='all', sort=['hubspot_company_id']) }}
{# Grain: one row per HubSpot company that is linked to a paying customer. This is the table Hightouch
   reads and pushes back into HubSpot (see docs/hightouch.md). It lives in dbt so that it is tested,
   documented and in the lineage graph like every other gold model. #}
select
    customers.hubspot_company_id,
    customers.current_plan as goldmine_plan,
    round(customers.current_mrr_cents / 100.0, 2) as goldmine_mrr_eur,
    customers.current_status as goldmine_subscription_status,
    customers.first_subscribed_on as goldmine_customer_since,
    coalesce(workspaces.is_active_last_28_days, false) as goldmine_active_last_28_days,
    coalesce(workspaces.messages_sent_last_28_days, 0) as goldmine_messages_last_28_days
from {{ ref('dim_customers') }} as customers
left join {{ ref('dim_workspaces') }} as workspaces on workspaces.workspace_id = customers.workspace_id
where customers.hubspot_company_id is not null
  and not customers.is_test_account
