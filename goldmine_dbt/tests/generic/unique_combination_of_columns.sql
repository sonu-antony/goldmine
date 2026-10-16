{% test unique_combination_of_columns(model, columns) %}
{# Fails for every combination of the given columns that appears more than once. #}
select {{ columns | join(', ') }}, count(*) as row_count
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
