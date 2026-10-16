{{ config(severity='warn') }}
-- Source problem: some won deals have no close date, and some close before they were created.
select deal_id, deal_stage, closed_on, created_at
from {{ ref('stg_hubspot__deals') }}
where (deal_stage = 'closed_won' and closed_on is null)
   or closed_on < cast(created_at as date)
