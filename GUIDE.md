# Project Guide — what I built and how

This is a plain-English tour of the repo, written for myself so I can explain every
part. Short words, no fluff.

---

## 1. What I was asked to do

JFrog makes **Artifactory** — a big store for software artifacts (Docker images,
npm packages, Maven jars, and so on). The analytics team wants to know what gets
downloaded, by whom, how repositories grow, and which packages gain traction. But
there is only raw data — no clean analytics tables yet.

The assignment had two parts:

- **Task 1** — design the analytics data model (a "Gold" layer) from raw data.
- **Task 2** — build a tool that turns a plain-language request into a ready dbt
  model, so analysts don't need a data engineer for every request.

The data is hypothetical. They grade the thinking, not whether code runs.

---

## 2. My approach — one system, not two parts

The key choice I made: **make Task 2 feed on Task 1.** The schema and rules I design
in Task 1 become the machine-readable "contract" that the Task 2 AI reads. So the
tool extends my model in the same language the model is written in. Most people hand
in two unrelated pieces; I handed in one connected system.

---

## 3. Repo tour

```
jfrog-artifactory-analytics/
├── README.md                    front door
├── GUIDE.md                     this file
├── task1_gold_model/
│   ├── docs/
│   │   ├── task1_gold_model.md   every model: grain, source, columns, use case
│   │   ├── erd.mermaid / erd.svg the ER diagram
│   │   └── assumptions.md        every assumption I made (incl. SCD)
│   └── models/gold/
│       ├── fct_download_events.sql   the one full SQL model
│       ├── fct_download_events.yml   its tests + column docs
│       └── gold_layer.yml            dbt schema for the other models
└── task2_ai_pipeline/
    ├── agents/
    │   ├── generator.md          prompt: "write the model"
    │   └── reviewer.md           prompt: "check the model"
    ├── context/                  the contract fed to the AI
    │   ├── raw_schema.yml         raw tables + columns (+ JSON payload fields)
    │   ├── gold_models.yml        GENERATED from Task 1 (do not hand-edit)
    │   ├── naming_conventions.md  naming + structure rules
    │   └── redshift_constraints.md DISTKEY/SORTKEY + SUPER rules
    ├── scripts/
    │   ├── generate_model.py      the pipeline: generate -> review
    │   ├── reviewer.py            the deterministic checks (testable)
    │   ├── build_context.py       builds gold_models.yml from Task 1 dbt yaml
    │   └── app.py                 a tiny Flask intake form
    ├── examples/                  sample request + generated output
    └── tests/test_reviewer.py     11 unit tests for the reviewer
```

---

## 4. Task 1 — the data model

### The shape (a star)

Facts in the middle (events), dimensions around them (descriptions). Facts are
**wide**: I copy the most-used attributes onto the fact so most queries need no
join. I keep the surrogate keys too, so a join is still possible when needed.

```
   dim_date   dim_repository   dim_user   dim_package
        \           \           /          /
         \           \         /          /
          +----> fct_download_events <----+     primary fact (full SQL written)
          +----> fct_deploy_events  <----+
                       |
               agg_repository_daily            one row per repo per day (fast dashboards)
```

### Where the data comes from

- **Snowplow** = behavioural events (a download, a deploy) → my **facts**.
- **Airbyte** = operational tables (repos, users, packages) → my **dimensions**.
- **Fullstory** = UI clicks → secondary, mostly noted in comments.

Simple rule: Snowplow says *what happened*, Airbyte says *what/who it is*.

### Grain (the contract of each table)

Every model states its grain in one line, e.g. "one row per download event". I keep
facts at one-row-per-event so nothing is lost. The only pre-summed table is the
daily aggregate. Each grain is enforced with a `unique` + `not_null` test.

### The one full SQL: `fct_download_events`

The pieces I can explain:

- **`config`** — `materialized='incremental'` (append only new events, don't rebuild
  a huge table), `dist='repository_sk'` and `sort=['download_date', ...]` (Redshift
  physical layout: fast joins + skip blocks outside the date range).
- **Parse the JSON** — Snowplow puts event fields in a `SUPER` column. I pull them
  into typed columns: `unstruct_event.size_bytes::bigint as bytes_sent`.
- **SCD2 as-of join** — I join dimensions on the version that was valid *at event
  time* (`downloaded_at between valid_from and valid_to`), not the current one. So a
  download made when a user was a bot keeps that fact.

### SCD (keeping history)

Airbyte overwrites rows, so raw dimensions only hold the current state. To keep
history I use **SCD Type 2** on `dim_repository` and `dim_user`
(`valid_from`/`valid_to`/`is_current`). Honest limit: history can only be built
*forward* from when snapshots start — I wrote that in `assumptions.md`.

---

## 5. Task 2 — the AI pipeline

### The flow

```
  analyst request                 (1) intake  -> examples/request.txt or web form
        |
        v
  [ context/ ] --> GENERATOR --> draft SQL + YAML        (2) built
                      |
                      v
                   REVIEWER  --- PASS --> ready for a PR  (4) stub
                      |  ^
                 FAIL |  | feedback (retry once)
                      v  |
                  (back to generator)                    (3) built
```

I built stages 2 and 3 fully, plus a light intake (web form). The PR step is a stub.

### The agents

- **`generator.md`** — tells the LLM: here is the context, don't invent columns,
  declare the grain, follow naming, and return a strict format. If the request is
  unclear, return `CLARIFY:` instead of guessing.
- **`reviewer.md`** — tells the LLM reviewer the checklist. But the *authoritative*
  review is code, not the LLM (see below).

### The reviewer is code, not vibes (`reviewer.py`)

A plain Python checker runs 6 checks. It's reliable and I unit-test it:

| # | Check | In plain words |
|---|-------|----------------|
| 1 | grain | first line is `-- GRAIN: ...` |
| 2 | naming | `fct_/dim_/agg_` prefix, snake_case |
| 3 | real columns | every `unstruct_event.x`, `source()` table, and `ref()` model + its columns exist |
| 4 | config | facts/aggregates declare `materialized` + `dist` + `sort` |
| 5 | references | uses `ref()`/`source()`, no hard-coded table names |
| 6 | tests | the `.yml` tests the grain key |

**Check 3 is the most important** — it's the anti-hallucination guard. The riskiest
thing an LLM does is invent a column; I catch that mechanically against
`raw_schema.yml` and `gold_models.yml`, not by trusting the model.

### Agent calls agent

In `generate_model.py`, the generate step calls the review step in-process. On a
FAIL it feeds the issues back and retries once. That's the "one agent calls another"
wiring.

### Safe by design

- **No silent garbage** — bad models are rejected before a PR.
- **Unclear request** → `CLARIFY:` question, not a guess.
- **Human in the loop** — the tool drafts; a person approves and merges.

### Runs anywhere

The pipeline picks the LLM by which key is set (`GEMINI_API_KEY` → Gemini,
else `ANTHROPIC_API_KEY` → Claude). With no key it runs in `--dry-run` using a
canned model, so the whole flow (and the review) can be shown offline. You do **not**
need dbt installed to run the pipeline — it produces files; dbt is only needed later
to actually build the models.

---

## 6. How the two tasks connect (and why there's no duplication)

The Gold models are described once — in the Task 1 dbt yaml. Task 2's catalog
(`context/gold_models.yml`) is **generated** from that by `build_context.py`:

```
task1 dbt yaml  --build_context.py-->  context/gold_models.yml  -->  AI generator + reviewer
(single source of truth)               (generated, never hand-edited)
```

So if I add a column in Task 1 and re-run the script, the AI's knowledge updates
automatically. In production the same script would read dbt's `manifest.json` /
`catalog.json` instead of the yaml directly.

---

## 7. How to run it

```bash
cd task2_ai_pipeline
pip install -r requirements.txt

# offline demo (no key) — shows generate + review end to end
python scripts/generate_model.py --request examples/request.txt --out examples/ --dry-run

# the reviewer tests (should say 11 passed)
python -m pytest tests -q

# rebuild the AI catalog from Task 1 after changing a model
python scripts/build_context.py

# web form for the intake stage
python scripts/app.py        # http://127.0.0.1:5000
```

For live generation: `export GEMINI_API_KEY=...` (or `ANTHROPIC_API_KEY`).

---

## 8. What I'd do next (honest limits)

- **Column checks aren't total** — I validate payload fields, sources, and columns
  pulled from simple `select ... from ref(X)` blocks, but not through joins or deep
  CTE chains. Next: a full column graph.
- **The LLM reviewer is advisory** — only the code checks block a model today.
- **Intake and PR are light/stubs** — next: a real GitHub PR via the API with the
  review report as the PR body.
- **No execution** — I don't run `dbt build`. Next: compile + run tests in CI before
  a merge is allowed.

I left these as stubs on purpose: the brief said to build one stage well, not
everything.

---

## 9. Questions I should be ready for

**Why Snowplow for facts, Airbyte for dimensions?** Snowplow is the event stream
("what happened"); Airbyte replicates operational state ("what/who it is").

**Why denormalize if it duplicates data?** At the Gold layer speed and simplicity
win. Copying hot attributes onto facts removes query-time joins; keys stay for the
rest.

**Where is SCD2?** On `dim_repository` and `dim_user`. The fact joins to the version
valid at event time, so history is correct.

**Why these DISTKEY/SORTKEY?** `dist=repository_sk` co-locates the repo rollup join;
`sort` by date because almost every query is time-bounded.

**Does it depend on dbt?** The output is dbt-format and conventions assume dbt
(named in the assignment stack), but the design isn't locked to it — swap the
prompts, context, and a few reviewer checks to target another framework. And you
don't need dbt installed to run the pipeline.

**How does it avoid inventing columns?** The reviewer checks every column against
`raw_schema.yml` / `gold_models.yml` in code and rejects anything unknown.

**Does it return data (e.g. a top-10 list)?** No — it returns the SQL model that
*would* compute it. The data is hypothetical; that matches the brief.
