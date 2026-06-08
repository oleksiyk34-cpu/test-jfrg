#!/usr/bin/env python3
"""
generate_model.py - the working pipeline.

Stage 2 (generation) and Stage 3 (review) end-to-end:

    analyst request + context/  --(generation agent)-->  SQL + YAML draft
                                 --(review agent)------>  PASS / FAIL
                                 --on FAIL: feed issues back, retry once-->

The generation agent calls the review agent PROGRAMMATICALLY (see generate()):
that is the "one agent calls another" wiring. Stages 1 (intake) and 4 (PR) are
stubbed.

Run live (needs ANTHROPIC_API_KEY):
    python scripts/generate_model.py --request examples/request.txt --out examples/
Run offline (no key) - uses a canned model so the pipeline can be demoed:
    python scripts/generate_model.py --request examples/request.txt --out examples/ --dry-run
"""

from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path

from reviewer import ConventionChecker

ROOT = Path(__file__).resolve().parents[1]
CTX = ROOT / "context"
AGENTS = ROOT / "agents"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_RETRIES = 2


def has_api_key() -> bool:
    """True if any supported provider key is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"))


# --------------------------------------------------------------------------- #
# Prompt assembly - this is where Task 1's design is injected as context.
# --------------------------------------------------------------------------- #
def build_prompt(request: str) -> tuple[str, str]:
    system = (AGENTS / "generator.md").read_text()
    context = "\n\n".join(
        f"### {name}\n```\n{(CTX / name).read_text()}\n```"
        for name in ("raw_schema.yml", "naming_conventions.md", "redshift_constraints.md")
    )
    user = f"{context}\n\n### Analyst request\n{request.strip()}\n"
    return system, user


# --------------------------------------------------------------------------- #
# The generation LLM call (live) and an offline canned fallback.
# --------------------------------------------------------------------------- #
def call_llm(system: str, user: str) -> str:
    """Provider-agnostic: uses Gemini if GEMINI_API_KEY is set, else Anthropic.
    SDKs are imported lazily so --dry-run and the tests need no SDK installed."""
    if os.environ.get("GEMINI_API_KEY"):
        return _call_gemini(system, user)
    return _call_anthropic(system, user)


def _call_anthropic(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=2000, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def _call_gemini(system: str, user: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(system_instruction=system),
        contents=user,
    )
    return resp.text


CANNED_RESPONSE = """MODEL_NAME: agg_repository_downloads_daily

```sql
-- GRAIN: one row per repository per day per actor_type.
-- Built from fct_download_events so it inherits clean, typed columns.
{{
  config(
    materialized = 'table',
    dist = 'repository_sk',
    sort = ['download_date']
  )
}}

with downloads as (

    select
        repository_sk,
        repo_key,
        download_date,
        actor_type,
        bytes_sent,
        is_success
    from {{ ref('fct_download_events') }}

)

select
    repository_sk,
    repo_key,
    download_date,
    actor_type,
    count(*)                                    as download_count,
    sum(bytes_sent)                             as bytes_downloaded,
    sum(case when is_success then 1 else 0 end) as successful_downloads
from downloads
group by 1, 2, 3, 4
```

```yaml
version: 2
models:
  - name: agg_repository_downloads_daily
    description: >
      Daily download activity per repository, split by actor type
      (human vs CI bot). One row per repository per day per actor_type.
    columns:
      - name: repository_sk
        description: FK to dim_repository.
        tests: [not_null]
      - name: download_date
        description: Activity date (UTC).
        tests: [not_null]
      - name: actor_type
        description: human | ci_bot | service | unknown.
        tests:
          - not_null
      - name: download_count
        description: Number of downloads in the day.
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [repository_sk, download_date, actor_type]
```
"""


# --------------------------------------------------------------------------- #
# Parse the strict output contract from the generator.
# --------------------------------------------------------------------------- #
def parse_response(text: str) -> dict:
    clarify = re.search(r"CLARIFY:\s*(.+)", text)
    if clarify and "```sql" not in text:
        return {"clarify": clarify.group(1).strip()}
    name = re.search(r"MODEL_NAME:\s*([A-Za-z0-9_]+)", text)
    sql = re.search(r"```sql\s*\n(.*?)```", text, re.S)
    yml = re.search(r"```ya?ml\s*\n(.*?)```", text, re.S)
    return {
        "clarify": None,
        "name": name.group(1) if name else "",
        "sql": sql.group(1).strip() if sql else "",
        "yml": yml.group(1).strip() if yml else "",
    }


# --------------------------------------------------------------------------- #
# Stage 3: the review agent (deterministic core; LLM judgment optional).
# --------------------------------------------------------------------------- #
def review(name: str, sql: str, yml: str):
    checker = ConventionChecker(CTX / "raw_schema.yml")
    return checker.check(name, sql, yml)


# --------------------------------------------------------------------------- #
# Stage 2: the generation agent - which CALLS the review agent.
# --------------------------------------------------------------------------- #
def generate(request: str, dry_run: bool) -> dict:
    system, user = build_prompt(request)
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        raw = CANNED_RESPONSE if dry_run else call_llm(system, user)
        parsed = parse_response(raw)

        if parsed.get("clarify"):
            return {"status": "clarify", "question": parsed["clarify"]}

        result = review(parsed["name"], parsed["sql"], parsed["yml"])   # agent -> agent
        last = (parsed, result)

        if result.passed:
            return {"status": "ok", "attempt": attempt, **parsed, "review": result}

        # Rejected: feed the reviewer's findings back and try once more.
        user += (
            "\n\n### Your previous draft was REJECTED by review. Fix these and "
            f"return a corrected model:\n{result.report()}\n"
        )

    parsed, result = last
    return {"status": "rejected", **parsed, "review": result}


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="NL request -> reviewed DBT model draft.")
    ap.add_argument("--request", required=True, help="Path to the analyst request (intake stub).")
    ap.add_argument("--out", default="examples", help="Output directory for .sql/.yml.")
    ap.add_argument("--dry-run", action="store_true", help="Use the canned model (no API key).")
    args = ap.parse_args()

    dry = args.dry_run or not has_api_key()
    if dry and not args.dry_run:
        print("! No ANTHROPIC_API_KEY or GEMINI_API_KEY found - running in --dry-run mode.\n")

    request = Path(args.request).read_text()
    print(f">> Intake request:\n{request.strip()}\n")

    res = generate(request, dry_run=dry)

    if res["status"] == "clarify":
        print(f"?? Generator needs clarification:\n   {res['question']}")
        return 2

    print(res["review"].report())

    if res["status"] == "rejected":
        print("\nxx Model rejected after retries. Not written. See issues above.")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "output.sql").write_text(res["sql"] + "\n")
    (out / "output.yml").write_text(res["yml"] + "\n")
    print(f"\nok Model '{res['name']}' passed review on attempt {res['attempt']}.")
    print(f"   Wrote {out/'output.sql'} and {out/'output.yml'}.")
    print("   [stub] Stage 4 would now open a pull request with these files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
