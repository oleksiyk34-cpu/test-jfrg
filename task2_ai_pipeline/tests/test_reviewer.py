"""
Unit tests for the review agent's deterministic checks (scripts/reviewer.py).

These guard the most valuable part of the pipeline: a bad model must be caught
before it reaches a PR. Run with:  pytest task2_ai_pipeline/tests
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from reviewer import ConventionChecker  # noqa: E402

SCHEMA = ROOT / "context" / "raw_schema.yml"
GOLD = ROOT / "context" / "gold_models.yml"


@pytest.fixture
def checker():
    return ConventionChecker(SCHEMA, GOLD)


# A clean model that should pass every check.
GOOD_SQL = """
-- GRAIN: one row per repository per day.
{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}
select repository_sk, download_date, count(*) as download_count
from {{ ref('fct_download_events') }}
group by 1, 2
"""
GOOD_YML = """
version: 2
models:
  - name: agg_repo_daily
    columns:
      - name: repository_sk
        tests: [not_null, unique]
"""


def errors(result):
    return [i for i in result.issues if i.severity == "error"]


def test_valid_model_passes(checker):
    result = checker.check("agg_repo_daily", GOOD_SQL, GOOD_YML)
    assert result.passed, result.report()


def test_bad_name_fails(checker):
    # no fct_/dim_/agg_ prefix
    result = checker.check("repo_daily", GOOD_SQL, GOOD_YML)
    assert not result.passed
    assert any(i.check == "naming" for i in errors(result))


def test_hallucinated_payload_field_fails(checker):
    sql = """-- GRAIN: one row per download.
{{ config(materialized='incremental', dist='repository_sk', sort=['download_date']) }}
select unstruct_event.totally_made_up::varchar as x
from {{ source('raw_snowplow', 'raw_snowplow__events') }}
"""
    result = checker.check("fct_x", sql, GOOD_YML)
    assert not result.passed
    assert any(i.check == "real_columns" for i in errors(result))


def test_unknown_source_table_fails(checker):
    sql = """-- GRAIN: one row per download.
{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}
select 1 from {{ source('raw_snowplow', 'raw_snowplow__does_not_exist') }}
"""
    result = checker.check("fct_x", sql, GOOD_YML)
    assert not result.passed
    assert any(i.check == "real_columns" for i in errors(result))


def test_missing_grain_fails(checker):
    sql = "{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}\nselect 1"
    result = checker.check("fct_x", sql, GOOD_YML)
    assert any(i.check == "grain" for i in errors(result))


def test_fact_without_dist_sort_fails(checker):
    sql = "-- GRAIN: one row per download.\n{{ config(materialized='table') }}\nselect 1"
    result = checker.check("fct_x", sql, GOOD_YML)
    assert not result.passed
    assert any(i.check == "config" for i in errors(result))


def test_missing_grain_test_fails(checker):
    yml_no_tests = "version: 2\nmodels:\n  - name: agg_repo_daily\n"
    result = checker.check("agg_repo_daily", GOOD_SQL, yml_no_tests)
    assert any(i.check == "tests" for i in errors(result))


def test_hardcoded_raw_table_fails(checker):
    sql = """-- GRAIN: one row per download.
{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}
select 1 from raw_snowplow__events
"""
    result = checker.check("fct_x", sql, GOOD_YML)
    assert any(i.check == "references" for i in errors(result))


# ---- Gold-model (Task 1) ref validation --------------------------------------

def test_ref_to_unknown_gold_model_fails(checker):
    sql = """-- GRAIN: one row per repo per day.
{{ config(materialized='table', dist='repository_sk', sort=['activity_date']) }}
select repository_sk from {{ ref('fct_does_not_exist') }}
"""
    result = checker.check("agg_x", sql, GOOD_YML)
    assert not result.passed
    assert any(i.check == "ref_columns" for i in errors(result))


def test_ref_column_not_in_gold_model_fails(checker):
    # 'made_up_col' is not a column of fct_download_events
    sql = """-- GRAIN: one row per repo per day.
{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}
select repository_sk, made_up_col
from {{ ref('fct_download_events') }}
"""
    result = checker.check("agg_x", sql, GOOD_YML)
    assert not result.passed
    assert any(i.check == "ref_columns" for i in errors(result))


def test_ref_valid_gold_columns_pass(checker):
    # all columns exist on fct_download_events; 'add a column' use case
    sql = """-- GRAIN: one row per download per actor.
{{ config(materialized='table', dist='repository_sk', sort=['download_date']) }}
with d as (
    select repository_sk, download_date, actor_type, bytes_sent
    from {{ ref('fct_download_events') }}
)
select repository_sk, download_date, actor_type,
       case when bytes_sent > 104857600 then true else false end as is_large_download
from d
"""
    result = checker.check("fct_downloads_with_size_flag", sql, GOOD_YML)
    assert result.passed, result.report()
