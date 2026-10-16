{{ config(severity='warn') }}
-- Source problem: a negative invoice is really a credit note entered in the wrong place.
select invoice_id, subscription_id, amount_cents
from {{ ref('stg_chargebee__invoice') }}
where amount_cents < 0
