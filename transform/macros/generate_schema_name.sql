{#
    prod: clean layer names (prod.silver). The prod catalog already isolates it.
    anything else: prefix with the target schema (dev.dbt_apetry_silver), so each
    developer and CI run gets its own schemas inside the dev catalog.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name == 'prod' -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
