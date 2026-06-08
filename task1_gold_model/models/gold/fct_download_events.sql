-- =============================================================================
-- fct_download_events
-- -----------------------------------------------------------------------------
-- GRAIN: one row per artifact download event.
-- The primary consumption fact for the Artifactory domain.
--
-- Source : raw_snowplow__events  WHERE event_name = 'artifact_download'
--          (one Snowplow event per download; payload in the SUPER unstruct_event)
-- Built straight from RAW (no Silver layer exists).
--
-- Design choices (see context/ for full rationale):
--   * WIDE & FLAT  -> repo/package/actor attributes are denormalized onto the
--                     fact so the common analyst query needs no join.
--   * SURROGATE KEYS kept too -> analysts can still join dims for extra columns.
--   * SCD2 AS-OF JOIN -> dims are joined on the version valid at event time, so
--                        history is accurate (not just "current" attributes).
--   * INCREMENTAL on derived_tstamp -> avoids full rebuilds on a large table.
--
-- Physical (2-node RA3.xlplus):
--   dist = repository_sk  -> co-locates with repo rollups (agg_repository_daily)
--                            and the heaviest GROUP BY (by repository).
--   sort = (download_date, repository_sk) -> date leads the sort key so the
--          common time-bounded query prunes blocks via zone maps.
-- =============================================================================

{{
  config(
    materialized       = 'incremental',
    unique_key         = 'download_event_id',
    incremental_strategy = 'delete+insert',
    dist               = 'repository_sk',
    sort               = ['download_date', 'repository_sk']
  )
}}

with

-- 1) Raw download events. event_name discriminates the action; payload is SUPER.
source_events as (

    select
        event_id,
        derived_tstamp,
        user_id,
        app_id,
        useragent,
        unstruct_event
    from {{ source('raw_snowplow', 'raw_snowplow__events') }}
    where event_name = 'artifact_download'

    {% if is_incremental() %}
      -- only pull events newer than what we already loaded
      and derived_tstamp > (select coalesce(max(downloaded_at), '1970-01-01') from {{ this }})
    {% endif %}

),

-- 2) Parse the SUPER payload into typed, flat columns.
--    SUPER values are dynamically typed -> cast every extracted field.
parsed as (

    select
        event_id                                              as download_event_id,
        derived_tstamp                                        as downloaded_at,
        cast(derived_tstamp as date)                          as download_date,
        user_id                                               as user_name,         -- natural key
        unstruct_event.repo_key::varchar(255)                 as repo_key,          -- natural key
        unstruct_event.package_name::varchar(500)             as package_name,      -- natural key
        unstruct_event.package_type::varchar(50)              as package_type,
        unstruct_event.package_version::varchar(100)          as package_version,
        unstruct_event.size_bytes::bigint                     as bytes_sent,
        unstruct_event.response_status::int                   as response_status,
        case
            when app_id = 'artifactory_ui'  then 'ui'
            when app_id = 'artifactory_cli' then 'cli'
            when app_id = 'artifactory_api' then 'api'
            else 'other'
        end                                                   as source_app
    from source_events

),

-- 3) Resolve dimension surrogate keys with SCD2 AS-OF joins:
--    pick the dim version whose validity window contains the event time.
--    (For events newer than the latest snapshot, this matches the current row.)
final as (

    select
        p.download_event_id,
        p.download_date,
        p.downloaded_at,

        -- surrogate keys (state as of event time)
        r.repository_sk,
        u.user_sk,
        pkg.package_sk,

        -- denormalized attributes (wide & flat -> no join needed at query time)
        p.repo_key,
        p.package_type,
        p.package_name,
        p.package_version,
        coalesce(u.actor_type, 'unknown')                     as actor_type,
        p.source_app,

        -- measures
        p.bytes_sent,
        p.response_status,
        (p.response_status between 200 and 299)               as is_success

    from parsed p

    left join {{ ref('dim_repository') }} r
        on  r.repo_key = p.repo_key
        and p.downloaded_at >= r.valid_from
        and p.downloaded_at <  coalesce(r.valid_to, timestamp '2999-01-01')

    left join {{ ref('dim_user') }} u
        on  u.user_name = p.user_name
        and p.downloaded_at >= u.valid_from
        and p.downloaded_at <  coalesce(u.valid_to, timestamp '2999-01-01')

    left join {{ ref('dim_package') }} pkg
        on  pkg.package_name = p.package_name
        and pkg.package_type = p.package_type

)

select * from final
