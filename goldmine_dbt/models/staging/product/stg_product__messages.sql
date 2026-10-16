{# No dedupe guard here on purpose: this is the largest table, and a window over tens of millions of
   rows on every read is too expensive. The loader replaces rows by id, and a unique test on
   message_id guards it instead. #}
select
    id as message_id,
    workspace_id,
    user_id,
    channel,
    direction,
    sent_at,
    cast(sent_at as date) as sent_date,
    created_at,
    updated_at,
    _loaded_at
from {{ source('product', 'product_messages') }}
