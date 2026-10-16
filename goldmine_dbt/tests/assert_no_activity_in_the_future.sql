-- Activity cannot exist for a day that has not happened yet.
select workspace_id, activity_date
from {{ ref('fct_workspace_activity_daily') }}
where activity_date > current_date
