{{ config(dist='all', sort=['customer_id']) }}
{# Grain: one row per resolved customer, with their current subscription and CRM company.
   Small dimension: a copy on every Redshift node (dist all) so joins from large facts never move data. #}
with companies as (
    select
        *,
        row_number() over (partition by chargebee_customer_id order by created_at asc, company_id asc) as company_rank
    from {{ ref('stg_hubspot__companies') }}
    where chargebee_customer_id is not null
)

select
    customers.customer_id,
    customers.customer_name,
    customers.workspace_id,
    workspaces.workspace_name,
    (customers.workspace_id is not null) as is_linked_to_workspace,
    (customers.workspace_id is not null and workspaces.workspace_id is null) as has_broken_workspace_link,
    subscriptions.plan_name as current_plan,
    subscriptions.subscription_status as current_status,
    coalesce(subscriptions.mrr_cents, 0) as current_mrr_cents,
    subscriptions.started_on as first_subscribed_on,
    subscriptions.cancelled_on,
    companies.company_id as hubspot_company_id,
    customers.duplicate_records_discarded,
    customers.is_test_account
from {{ ref('int_customers__resolved') }} as customers
left join {{ ref('int_subscriptions__enriched') }} as subscriptions on subscriptions.customer_id = customers.customer_id
left join {{ ref('stg_product__workspaces') }} as workspaces on workspaces.workspace_id = customers.workspace_id
left join companies on companies.chargebee_customer_id = customers.customer_id and companies.company_rank = 1
