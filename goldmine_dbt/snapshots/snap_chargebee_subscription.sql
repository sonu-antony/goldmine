{% snapshot snap_chargebee_subscription %}

{{
    config(
        target_schema='snapshots',
        unique_key='subscription_id',
        strategy='timestamp',
        updated_at='updated_at'
    )
}}

{# Chargebee overwrites a subscription row on every change. This snapshot keeps every version we saw:
   one row per subscription per version, with dbt_valid_from and dbt_valid_to. It only sees the
   state at the moment it runs, so two changes between two runs show only the last one. The events
   log (int_subscription_state_monthly) is what recovers history from before the first run. #}
select * from {{ ref('stg_chargebee__subscription') }}

{% endsnapshot %}
