-- Rates must be between 0 and a plausible ceiling. A rate outside this means a bad join or a bad definition.
select month_start, logo_churn_rate, gross_revenue_churn_rate, net_revenue_retention, gross_revenue_retention
from {{ ref('fct_saas_metrics_monthly') }}
where logo_churn_rate not between 0 and 1
   or gross_revenue_churn_rate not between 0 and 1
   or gross_revenue_retention not between 0 and 1
   or net_revenue_retention not between 0 and 3
