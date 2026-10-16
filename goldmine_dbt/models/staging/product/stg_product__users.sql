{# The product team once renamed users.email to email_address. The loader adds new columns to raw and
   keeps the old one, so raw can hold either or both. Staging accepts both, so one rename upstream
   cannot empty the column downstream. #}
{%- set raw_columns = [] -%}
{%- if execute -%}
    {%- set raw_columns = adapter.get_columns_in_relation(source('product', 'product_users')) | map(attribute='name') | list -%}
{%- endif -%}

select
    id as user_id,
    workspace_id,
    {% if 'email_address' in raw_columns -%}
    lower(trim(coalesce(email_address, email))) as email,
    {%- else -%}
    lower(trim(email)) as email,
    {%- endif %}
    role as user_role,
    created_at,
    updated_at,
    _loaded_at
from {{ dedupe_latest(source('product', 'product_users')) }} as app_user
