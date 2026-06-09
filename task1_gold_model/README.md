# Task 1 — Gold Layer Data Model

A wide, query-friendly analytics model for the Artifactory domain, built from raw
Redshift tables only (there is no Silver layer — I build the whole path to Gold).

## In one line

Two event facts (download, deploy) in the middle, four dimensions around them, and
one daily rollup for fast dashboards. Facts are wide: the attributes people filter
on most are denormalized onto the fact, so common queries need no joins.

```
        dim_date   dim_repository   dim_user   dim_package
             \          |             |          /
              \         |             |         /
               +--> fct_download_events <--+         (the primary fact)
               +--> fct_deploy_events  <--+
                         |
                  agg_repository_daily  (one row per repo per day)
```

## What's here

- **`docs/task1_gold_model.md`** — model definitions: every model, its grain,
  source, and key columns, plus which use case each one serves.
- **`docs/erd.mermaid`** / **`docs/erd.svg`** — the ER diagram (same picture, two
  formats).
- **`docs/assumptions.md`** — every design assumption, including the SCD strategy.
- **`models/gold/fct_download_events.sql`** — the one full SQL model (primary fact).
- **`models/gold/fct_download_events.yml`** — its tests and column docs.
- **`models/gold/gold_layer.yml`** — the dbt schema for the other designed models.
  This file (plus `fct_download_events.yml`) is the single source of truth that
  Task 2 reads to build its model catalog.

The raw sources these models are built from are documented in
`../task2_ai_pipeline/context/raw_schema.yml`.
