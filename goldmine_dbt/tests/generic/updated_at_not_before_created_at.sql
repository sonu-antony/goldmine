{% test updated_at_not_before_created_at(model, created_column='created_at', updated_column='updated_at') %}
{# Returns the rows where a record claims to have been updated before it was created. #}
select *
from {{ model }}
where {{ updated_column }} < {{ created_column }}
{% endtest %}
