-- GRAIN: one row per repository per day per actor_type.
-- Built from fct_download_events so it inherits clean, typed columns.
{{
  config(
    materialized = 'table',
    dist = 'repository_sk',
    sort = ['download_date']
  )
}}

with downloads as (

    select
        repository_sk,
        repo_key,
        download_date,
        actor_type,
        bytes_sent,
        is_success
    from {{ ref('fct_download_events') }}

)

select
    repository_sk,
    repo_key,
    download_date,
    actor_type,
    count(*)                                    as download_count,
    sum(bytes_sent)                             as bytes_downloaded,
    sum(case when is_success then 1 else 0 end) as successful_downloads
from downloads
group by 1, 2, 3, 4
