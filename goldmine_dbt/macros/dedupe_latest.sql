{# Guard against repeated raw rows: keep the latest copy of each key.
   Raw is loaded by delete-then-insert, so repeats should not happen, but Redshift does not enforce
   primary keys, so a retried load could leave two copies. Staging makes sure downstream never sees them. #}
{% macro dedupe_latest(source_relation, key='id') %}
(
    select ranked.*
    from (
        select
            raw_rows.*,
            row_number() over (
                partition by raw_rows.{{ key }}
                order by raw_rows.updated_at desc, raw_rows._loaded_at desc
            ) as _row_number
        from {{ source_relation }} as raw_rows
    ) as ranked
    where ranked._row_number = 1
)
{% endmacro %}
