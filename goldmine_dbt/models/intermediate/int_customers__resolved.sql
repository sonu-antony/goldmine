{# Grain: one row per real-world customer.
   The source can hold two customer records for the same workspace (one empty copy). This model picks
   the survivor with an explicit rule: the record that has subscriptions, then the oldest one.
   Customers without a workspace are each kept, because there is nothing to compare them on. #}
with customers as (
    select
        *,
        coalesce(cast(workspace_id as varchar), 'customer_' || cast(customer_id as varchar)) as identity_key
    from {{ ref('stg_chargebee__customer') }}
),

subscription_counts as (
    select customer_id, count(*) as subscription_count
    from {{ ref('stg_chargebee__subscription') }}
    group by customer_id
),

ranked as (
    select
        customers.*,
        coalesce(subscription_counts.subscription_count, 0) as subscription_count,
        row_number() over (
            partition by customers.identity_key
            order by coalesce(subscription_counts.subscription_count, 0) desc, customers.created_at asc, customers.customer_id asc
        ) as customer_rank,
        count(*) over (partition by customers.identity_key) as records_for_identity
    from customers
    left join subscription_counts on subscription_counts.customer_id = customers.customer_id
)

select
    customer_id,
    customer_name,
    workspace_id,
    subscription_count,
    records_for_identity - 1 as duplicate_records_discarded,
    customer_name like 'TEST ACCOUNT%' as is_test_account,
    created_at,
    updated_at
from ranked
where customer_rank = 1
