{{ config(severity='warn') }}
-- Source problem: a server with a wrong clock stamps messages in the future.
select message_id, workspace_id, sent_at
from {{ ref('stg_product__messages') }}
where sent_at > current_timestamp
