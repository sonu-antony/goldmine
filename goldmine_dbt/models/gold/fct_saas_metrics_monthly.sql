{{ config(dist='all', sort=['month_start']) }}
{# Grain: one row per month. The company-level SaaS metrics, defined once here and used by every dashboard.
     logo churn rate          customers lost / customers at the start of the month
     gross revenue churn      (churned + contraction) / opening MRR. Pauses are not churn.
     net revenue retention    revenue at month end from customers who were paying at month start,
                              including their expansion, divided by opening MRR
     gross revenue retention  the same without expansion
   Redshift: tiny table, so a copy on every node (dist all) avoids data movement in joins. #}
with movements as (
    select * from {{ ref('fct_mrr_movements') }}
),

totals as (
    select
        month_start,
        sum(previous_mrr_cents) as opening_mrr_cents,
        sum(new_mrr_cents) as new_mrr_cents,
        sum(expansion_mrr_cents) as expansion_mrr_cents,
        sum(contraction_mrr_cents) as contraction_mrr_cents,
        sum(churned_mrr_cents) as churned_mrr_cents,
        sum(reactivated_mrr_cents) as reactivated_mrr_cents,
        sum(paused_mrr_cents) as paused_mrr_cents,
        sum(resumed_mrr_cents) as resumed_mrr_cents,
        sum(mrr_cents) as closing_mrr_cents,
        sum(case when previous_mrr_cents > 0 then 1 else 0 end) as opening_customers,
        sum(case when mrr_cents > 0 then 1 else 0 end) as closing_customers,
        sum(case when movement_type = 'new' then 1 else 0 end) as new_customers,
        sum(case when movement_type = 'churned' then 1 else 0 end) as churned_customers
    from movements
    group by month_start
)

select
    *,
    cast(churned_customers as decimal(18, 6)) / nullif(opening_customers, 0) as logo_churn_rate,
    cast(churned_mrr_cents + contraction_mrr_cents as decimal(18, 6)) / nullif(opening_mrr_cents, 0) as gross_revenue_churn_rate,
    cast(opening_mrr_cents + expansion_mrr_cents - contraction_mrr_cents - churned_mrr_cents - paused_mrr_cents as decimal(18, 6))
        / nullif(opening_mrr_cents, 0) as net_revenue_retention,
    cast(opening_mrr_cents - contraction_mrr_cents - churned_mrr_cents - paused_mrr_cents as decimal(18, 6))
        / nullif(opening_mrr_cents, 0) as gross_revenue_retention
from totals
