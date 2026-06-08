# Redshift Physical Modeling Constraints

Target cluster: **2-node RA3.xlplus**. These rules are injected into the modeling
agent so generated facts come with sensible physical hints, and are checked by the
review agent.

## Distribution (`DISTKEY` / `DISTSTYLE`)

- Pick the `DISTKEY` to **co-locate the most frequent / most expensive join**.
  For event facts, that is usually the highest-cardinality dimension key the fact
  is most often joined or grouped on.
- Small dimensions (< ~1–2M rows): `DISTSTYLE ALL` so they are replicated to every
  node and joins need no redistribution.
- Avoid `DISTSTYLE EVEN` on tables that are routinely joined — it forces broadcast/
  redistribution at query time.
- A bad `DISTKEY` causes `DS_BCAST_INNER` / `DS_DIST_BOTH` in `STL_EXPLAIN`; the
  goal is `DS_DIST_NONE` for the hot join.

## Sort (`SORTKEY`)

- Lead the `SORTKEY` with the column used in range filters — almost always the
  event date/timestamp (`download_date`), so time-bounded analyst queries prune
  blocks via zone maps.
- Add a secondary sort column matching the most common `GROUP BY` (e.g.
  `repository_sk`) when it helps.
- Compound sort key is the default; reserve interleaved for genuinely multi-axis
  filtering (it has higher VACUUM cost).

## Encoding & maintenance

- Let Redshift apply `ENCODE AUTO`, or specify `az64` for numerics/timestamps and
  `zstd` for varchars on very large tables.
- Large facts are incremental (`materialized='incremental'`) on `derived_tstamp`
  to avoid full rebuilds.
- Flag tables that need periodic `VACUUM` / `ANALYZE` after heavy loads.

## SUPER / semi-structured

- Snowplow payloads are `SUPER`. Extract with PartiQL dot-notation
  (`e.unstruct_event.artifact_path`) or `JSON_EXTRACT_PATH_TEXT(...)`.
- Cast extracted values explicitly (`::varchar`, `::bigint`) — `SUPER` values are
  dynamically typed and will not compare/aggregate correctly otherwise.
- Materialize parsed columns in the fact so analysts never touch raw JSON.
