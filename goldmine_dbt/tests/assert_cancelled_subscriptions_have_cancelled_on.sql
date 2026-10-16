{{ config(severity='warn') }}
-- Source problem: some subscriptions are cancelled but the cancellation date was never filled in.
select subscription_id, subscription_status, cancelled_on
from {{ ref('stg_chargebee__subscription') }}
where subscription_status = 'cancelled'
  and cancelled_on is null
