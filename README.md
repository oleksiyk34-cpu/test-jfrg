# JFrog Artifactory - Data Engineering Home Assignment

Two tasks, one repo:

- **[`task1_gold_model/`](./task1_gold_model)** - a Gold-layer analytics model for
  the Artifactory domain, built straight from raw Redshift tables.
- **[`task2_ai_pipeline/`](./task2_ai_pipeline)** - a semi-automated pipeline that
  turns an analyst's plain-language request into a DBT model draft (SQL + YAML),
  reviewed and ready for a PR.

## How the two tasks connect

This is the core idea: **Task 1 is the ground truth that Task 2 feeds on.**

The schema, naming rules, and Redshift constraints we designed in Task 1 live in
`task2_ai_pipeline/context/` as machine-readable files. The Task 2 agent reads
exactly those files, so every model it generates follows the same conventions and
only references columns that actually exist. The data model and the tool that
extends it speak the same language.

```
Task 1 design  ->  context/ files  ->  Task 2 agent generates new models
(human-made)       (the contract)      (machine-made, same conventions)
```

## Quick start

- Task 1: open `task1_gold_model/docs/` (model definitions, ERD, assumptions) and
  `task1_gold_model/models/gold/` (the SQL stub).
- Task 2: see `task2_ai_pipeline/README.md` to run the pipeline.
