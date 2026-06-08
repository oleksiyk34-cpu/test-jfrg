# Task 1 - Gold Layer Data Model

A wide, analyst-friendly model for the Artifactory domain, built straight from
raw Redshift tables (no Silver layer). Facts come from Snowplow events,
dimensions from Airbyte tables. See the diagram in `erd.mermaid` and the full
list of assumptions in `assumptions.md`.

## Design idea in one line

Two event facts (download, deploy) sit in the middle. Four dimensions describe
them. One daily rollup makes dashboards fast. Facts are wide: the attributes
people filter on most (repo type, package, actor type) are copied onto the fact,
so common queries need no joins.

## How it covers the four use cases

| Use case | Model(s) used |
|---|---|
| Artifact usage - most downloaded, by whom, from where | `fct_download_events` + `dim_user`, `dim_repository` |
| Repository health - storage growth, traffic | `agg_repository_daily` + `dim_repository` |
| User & pipeline activity - human vs CI bot, power users | `fct_download_events` / `fct_deploy_events` + `dim_user.actor_type` |
| Package adoption - gaining or losing traction | `fct_download_events` + `dim_package` + `dim_date` |

## Models

### Facts

**`fct_download_events`** - the primary fact (full SQL in `models/gold/`).
Grain: one row per download event.
Source: `raw_snowplow__events` where `event_name = 'artifact_download'`.
Key columns: `download_event_id`, `downloaded_at`, the four dimension keys,
denormalized `repo_key` / `package_type` / `package_name` / `package_version` /
`actor_type` / `source_app`, and measures `bytes_sent`, `response_status`,
`is_success`.

**`fct_deploy_events`** - the production signal.
Grain: one row per deploy (upload) event.
Source: `raw_snowplow__events` where `event_name = 'artifact_deploy'`.
Key columns: dimension keys plus `size_bytes`, `sha256`.

**`fct_ui_interactions`** - secondary, UX only (defined, no SQL stub).
Grain: one row per Fullstory UI event.
Source: `raw_fullstory__events`. Used for UI engagement, not artifact consumption.

### Aggregate

**`agg_repository_daily`** - keeps dashboards fast.
Grain: one row per repository per day.
Built from the two facts plus a daily storage snapshot from
`raw_artifactory__items`. Holds `download_count`, `deploy_count`,
`bytes_downloaded`, `storage_bytes`, `distinct_users`.

### Dimensions

**`dim_repository`** - one row per repository version. SCD Type 2
(`valid_from`, `valid_to`, `is_current`), because repo type/mode can change.

**`dim_user`** - one row per user version. SCD Type 2. Adds the derived
`actor_type` (`human` / `ci_bot` / `service`) since raw has no such flag.

**`dim_package`** - one row per package. SCD Type 1 (no history needed).

**`dim_date`** - standard calendar, one row per day.

## Why these grains

The grain is the contract of each table. Event facts stay at one-row-per-event so
no detail is lost and any rollup is possible later. The aggregate is the only
pre-summed table, and its grain (repo per day) matches how health dashboards are
read. Each grain is enforced with a `unique` + `not_null` test on its key.

## SCD note

Raw dimensions are overwritten by Airbyte, so they hold current state only.
History is therefore captured in Gold, going forward, via `dbt snapshots` on
`dim_repository` and `dim_user`. Past changes that raw never kept cannot be
rebuilt - this is documented as a known limitation.

## Event mapping (raw -> fact)

`fct_download_events` reads Snowplow rows where `event_name='artifact_download'`
and pulls fields out of the `unstruct_event` SUPER payload
(`artifact_path`, `repo_key`, `package_type`, `package_name`, `package_version`,
`size_bytes`, `response_status`). Deploys map the same way with
`event_name='artifact_deploy'`. Fullstory rows map to `fct_ui_interactions` by
`event_type`. Exact field paths are in `raw_schema.yml`.
