{# A fingerprint of the station list and the vocabulary, made of their whole rows. The hourly
   model stores it on every row; when either seed changes, the fingerprint changes and the next
   build redoes every hour, because which lines are read and which values are valid depend on
   both. The row aliases must not be the name of a column, or that column is taken instead. #}
{% macro metadata_fingerprint() %}
    md5(
        (select string_agg(station_row::varchar, '|' order by station_row::varchar)
            from {{ ref('registry') }} as station_row)
        || '#'
        || (select string_agg(vocabulary_row::varchar, '|' order by vocabulary_row::varchar)
            from {{ ref('parameter') }} as vocabulary_row)
    )
{% endmacro %}
