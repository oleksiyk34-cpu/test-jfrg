# Task 1 - Gold Layer Data Model

A wide, query-friendly analytics model for the Artifactory domain, built from raw
Redshift tables only (no Silver layer).

## What's here

- **`docs/task1_gold_model.md`** - model definitions: every model, its grain,
  source, and key columns, plus which use case each one serves.
- **`docs/erd.mermaid`** / **`docs/erd.svg`** - the entity-relationship diagram
  (same diagram, two formats).
- **`docs/assumptions.md`** - every design assumption, including the SCD strategy.
- **`models/gold/fct_download_events.sql`** - full SQL stub for the primary fact.
- **`models/gold/fct_download_events.yml`** - its tests and column docs.

## In one line

Two event facts (download, deploy) in the middle, four dimensions around them, one
daily rollup for fast dashboards. Facts are wide: common attributes are
denormalized on so most queries need no joins.

The raw sources these models are built from are documented in
`../task2_ai_pipeline/context/raw_schema.yml`.
