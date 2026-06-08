# Naming & Modeling Conventions

These conventions govern every Gold model. They are enforced by the **review
agent** in Task 2 (a generated model that violates them is rejected before PR),
so they are written to be checkable, not just aspirational.

## 1. Model names

| Layer        | Prefix   | Example                  | Meaning                                  |
|--------------|----------|--------------------------|------------------------------------------|
| Fact         | `fct_`   | `fct_download_events`    | Measurable business process / event grain |
| Dimension    | `dim_`   | `dim_repository`         | Descriptive entity, one row per thing     |
| Aggregate    | `agg_`   | `agg_repository_daily`   | Pre-aggregated rollup for performance      |

- All lowercase `snake_case`. No camelCase, no spaces.
- Fact and aggregate names are **plural where they count events** (`..._events`),
  dimensions are **singular** (`dim_repository`, not `dim_repositories`).
- Aggregates encode their grain in the suffix: `_daily`, `_weekly`, `_monthly`.

## 2. Column names

- Surrogate keys: `<entity>_sk` (e.g. `repository_sk`), generated with a hash of
  the natural key(s). Stable, integer-free, join-friendly.
- Natural / business keys: `<entity>_key` or the source's own id
  (e.g. `repo_key`, `user_name`).
- Foreign keys carry the referenced surrogate key name unchanged
  (`fct_download_events.repository_sk` -> `dim_repository.repository_sk`).
- Timestamps end in `_at` (`downloaded_at`); dates end in `_date`
  (`download_date`); booleans start with `is_` / `has_` (`is_ci_bot`).
- Measures are explicit nouns: `bytes_sent`, `download_count`, `size_bytes`.
- No reserved words; no ambiguous abbreviations.

## 3. Grain

- **Every model declares its grain in one sentence** at the top of the SQL and in
  its `.yml` `description`. Example: "one row per artifact download event".
- The grain must be enforceable by a `unique` / `not_null` test on the grain key.

## 4. Gold-layer shape

- **Wide and flat beats normalized.** Denormalize descriptive attributes onto
  facts where it removes a query-time join (e.g. carry `package_type` and
  `repo_rclass` directly on `fct_download_events`).
- Keep surrogate keys too, so analysts *can* still join to dimensions for
  attributes we did not pre-join.
- No model joins more than necessary at query time; push joins upstream.

## 5. Redshift physical conventions

- Large fact tables declare `DISTKEY` and `SORTKEY` in a config block, justified
  in a comment (see `redshift_constraints.md`).
- Dimensions are usually `DISTSTYLE ALL` (small, broadcast to every node).
- Date/timestamp columns used in filters belong in the `SORTKEY`.

## 6. dbt structure

- One model = one file, named exactly as the model.
- Every model has a sibling entry in a `.yml` with: `description`, grain note,
  column descriptions, and at least the grain-key `unique` + `not_null` tests.
- Sources are referenced via `{{ source('raw_<system>', 'raw_<system>__<table>') }}`.
- Models reference each other via `{{ ref('...') }}`, never hard-coded names.

## 7. SCD policy

- Dimensions that need history use **SCD Type 2** with `valid_from`, `valid_to`,
  `is_current`, materialized via `dbt snapshots`. See `assumptions.md`.
- Dimensions that do not need history use **SCD Type 1** (overwrite).
