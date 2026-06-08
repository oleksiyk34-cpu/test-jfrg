"""
reviewer.py - the deterministic core of the Review Agent.

It mechanically enforces the convention checklist (see agents/reviewer.md) against
a generated model. These checks are authoritative; the LLM reviewer adds judgment
on top. Kept import-light (only PyYAML) so it is easy to unit test.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class Issue:
    severity: str   # "error" | "warning"
    check: str
    message: str


@dataclass
class ReviewResult:
    passed: bool
    issues: list

    def report(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        lines = [f"VERDICT: {verdict}", "ISSUES:"]
        if not self.issues:
            lines.append("- none")
        for i in self.issues:
            lines.append(f"- [severity: {i.severity}] {i.check}: {i.message}")
        return "\n".join(lines)


class ConventionChecker:
    """Loads the raw schema once, then checks any (model_name, sql, yml)."""

    NAME_RE = re.compile(r"^(fct|dim|agg)_[a-z0-9_]+$")

    def __init__(self, schema_path: str | Path):
        schema = yaml.safe_load(Path(schema_path).read_text())
        self.tables: set[str] = set()
        self.columns: set[str] = set()
        self.payload_fields: set[str] = set()
        for src in schema.get("sources", []):
            for t in src.get("tables", []):
                self.tables.add(t["name"])
                for c in t.get("columns", []):
                    self.columns.add(c["name"])
                for _, pdef in (t.get("payload_schemas") or {}).items():
                    for f in pdef.get("fields", []):
                        self.payload_fields.add(f["path"].split(".")[-1])

    # ---- individual checks -------------------------------------------------

    def _check_grain(self, sql, issues):
        if not re.search(r"--\s*GRAIN\s*:", sql, re.I):
            issues.append(Issue("error", "grain",
                "No grain declared. Add a first comment line: '-- GRAIN: one row per ...'."))

    def _check_naming(self, name, issues):
        if not self.NAME_RE.match(name):
            issues.append(Issue("error", "naming",
                f"Model name '{name}' must be snake_case and start with fct_/dim_/agg_."))

    def _check_real_columns(self, sql, issues):
        # Hallucination guard #1: SUPER payload fields must exist.
        for field in re.findall(r"unstruct_event\.(\w+)", sql):
            if field not in self.payload_fields:
                issues.append(Issue("error", "real_columns",
                    f"unstruct_event.{field} is not in raw_schema.yml (hallucinated payload field)."))
        # Hallucination guard #2: source() tables must exist.
        for _src, table in re.findall(
                r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", sql):
            if table not in self.tables:
                issues.append(Issue("error", "real_columns",
                    f"source table '{table}' does not exist in raw_schema.yml."))

    def _check_config(self, name, sql, issues):
        if not name.startswith(("fct_", "agg_")):
            return
        m = re.search(r"config\((.*?)\)", sql, re.S)
        if not m:
            issues.append(Issue("error", "config",
                "Fact/aggregate must declare a {{ config(...) }} block."))
            return
        block = m.group(1)
        if "materialized" not in block:
            issues.append(Issue("error", "config", "config() is missing 'materialized'."))
        for key in ("dist", "sort"):
            if key not in block:
                issues.append(Issue("error", "config",
                    f"Fact/aggregate config() is missing '{key}' (Redshift physical hint)."))

    def _check_references(self, sql, issues):
        if re.search(r"\b(from|join)\s+raw_\w+", sql, re.I):
            issues.append(Issue("error", "references",
                "Hard-coded raw table. Use {{ source('raw_<system>', '<table>') }}."))
        if re.search(r"select\s+\*\s+from\s+\{\{", sql, re.I):
            issues.append(Issue("warning", "references",
                "select * straight from a ref/source. Select explicit columns."))

    def _check_tests(self, yml_text, issues):
        has_grain_test = (
            ("unique" in yml_text and "not_null" in yml_text)
            or "unique_combination" in yml_text
        )
        if not has_grain_test:
            issues.append(Issue("error", "tests",
                "The .yml must test the grain key: unique + not_null, "
                "or a unique-combination test for a composite grain."))

    # ---- public entrypoint -------------------------------------------------

    def check(self, model_name: str, sql: str, yml_text: str) -> ReviewResult:
        issues: list[Issue] = []
        self._check_grain(sql, issues)
        self._check_naming(model_name, issues)
        self._check_real_columns(sql, issues)
        self._check_config(model_name, sql, issues)
        self._check_references(sql, issues)
        self._check_tests(yml_text, issues)
        passed = not any(i.severity == "error" for i in issues)
        return ReviewResult(passed=passed, issues=issues)
