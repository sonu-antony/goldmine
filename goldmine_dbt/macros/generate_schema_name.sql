{# Build each layer into exactly the schema named in dbt_project.yml (staging, intermediate, gold),
   instead of dbt's default "<target schema>_<custom schema>". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
