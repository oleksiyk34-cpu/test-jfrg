# Assumptions

There is no reference schema. Every design choice below is an explicit,
documented assumption. Where the assignment FAQ invites it, we state the
assumption and continue.

## A. Source & grain

1. **Downloads are the primary fact grain.** Snowplow fires exactly one event per
   artifact download, with the artifact path and metadata in the
   `unstruct_event` SUPER payload. `fct_download_events` is therefore one row per
   download event. (Directly per the assignment FAQ.)
2. **Uploads/deploys are the production fact.** `event_name = 'artifact_deploy'`
   fires once per new artifact version pushed; modeled as `fct_deploy_events`.
3. **Snowplow = facts, Airbyte = dimensions.** Behavioral "what happened" comes
   from Snowplow; descriptive "what/who it is" comes from Airbyte-replicated
   operational tables.
4. **Fullstory is secondary (UX only).** It measures UI engagement, not artifact
   consumption, so it feeds an optional `fct_ui_interactions`, not the core facts.

## B. Identity (human vs CI bot)

5. RAW has **no** human-vs-bot flag. We derive `actor_type`
   (`human` | `ci_bot` | `service`) in `dim_user` using heuristics:
   - `realm = 'api_key'` or null/service-pattern email -> likely non-human;
   - `user_name` matching `%-ci`, `%-bot`, `svc-%`, `jenkins%`, `gha-%` -> `ci_bot`;
   - `app_id = 'artifactory_api'/'artifactory_cli'` with no UI sessions reinforces
     the classification;
   - everything else defaults to `human`.
   The rule set is centralized so it can be tuned without touching facts.

## C. Storage vs traffic (size lives in two places — on purpose)

6. **Storage size** (how much a repo occupies *now*) comes from
   `raw_artifactory__items.size_bytes` — current-state stock.
7. **Traffic bytes** (bytes moved by downloads) come from
   `unstruct_event.size_bytes` on the download event — flow.
   These answer different questions and are never conflated.

## D. Package identity

8. A **package** is the logical grouping of artifacts sharing a name across
   versions (`my-service:1.0`, `my-service:2.0`). `package_name` /
   `package_version` are parsed from the artifact path; we assume the path
   convention is consistent per `package_type`.

## E. Time

9. Analytics uses Snowplow `derived_tstamp` (true event time), not
   `collector_tstamp` (load/ordering time).
10. Daily grains bucket on `derived_tstamp` in **UTC**.

## F. SCD strategy (the key historical-data decision)

11. Airbyte replication **overwrites** rows, so RAW dimensions hold current state
    only — no built-in history.
12. `dim_repository` and `dim_user` need history (repo `rclass`/`package_type` can
    change; user `realm`/`is_admin`/derived `actor_type` can change). They use
    **SCD Type 2** (`valid_from`, `valid_to`, `is_current`) materialized via
    `dbt snapshots`.
13. **Honest limitation:** because RAW overwrites, true history can only be built
    *forward* from when snapshots begin — past changes that RAW never preserved
    cannot be reconstructed. Until snapshots accumulate, dimensions behave like
    SCD Type 1.
14. `dim_package` and `dim_date` do not need history -> SCD Type 1 / static.

## G. Scope / out of scope

15. No real JFrog data is used; all names and payload shapes are hypothetical.
16. We build one fact end-to-end (`fct_download_events`) and define the rest; we
    do not run dbt or Redshift (per the assignment).
