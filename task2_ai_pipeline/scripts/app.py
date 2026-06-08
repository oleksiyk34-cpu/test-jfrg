#!/usr/bin/env python3
"""
app.py - Stage 1 (Intake) as a tiny web form.

An analyst types a plain-language request, clicks Generate, and sees the model the
pipeline produced plus the review verdict. It just wraps generate() from
generate_model.py - the same generation + review logic the CLI uses.

Run:
    cd task2_ai_pipeline
    pip install flask
    python scripts/app.py            # open http://127.0.0.1:5000
Without ANTHROPIC_API_KEY it runs in dry-run (returns a canned sample model).
"""

import os
from pathlib import Path
from flask import Flask, request, render_template_string

from generate_model import generate, has_api_key, ROOT

app = Flask(__name__)
DRY = not has_api_key()
GEN_DIR = ROOT / "generated"   # staging area for drafts, ready for review/PR

PAGE = """
<!doctype html><title>New Gold Model</title>
<style>
 body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px}
 textarea{width:100%;height:110px;font-size:15px;padding:8px}
 button{padding:9px 18px;font-size:15px;margin-top:8px;cursor:pointer}
 pre{background:#f5f5f5;padding:12px;border-radius:6px;overflow:auto}
 .pass{color:#067d2f;font-weight:700}.fail{color:#c0392b;font-weight:700}
 .banner{background:#fff7e6;border:1px solid #f0c36d;padding:8px 12px;border-radius:6px}
</style>
<h2>Request a new Gold model</h2>
{% if dry %}<p class="banner">Dry-run mode (no API key): returns a canned sample model regardless of input.</p>{% endif %}
<form method="post">
 <textarea name="request" placeholder="e.g. Daily download counts per repository, split by human vs CI bot.">{{ request_text or '' }}</textarea><br>
 <button type="submit">Generate</button>
</form>
{% if result %}
 <hr>
 {% if result.status == 'clarify' %}
   <p class="fail">Needs clarification:</p><p>{{ result.question }}</p>
 {% else %}
   <p class="{{ 'pass' if result.review.passed else 'fail' }}">
     {{ 'PASS' if result.review.passed else 'FAIL' }} - model {{ result.name }}</p>
   {% if result.review.issues %}<ul>
     {% for i in result.review.issues %}<li>[{{ i.severity }}] {{ i.check }}: {{ i.message }}</li>{% endfor %}
   </ul>{% endif %}
   {% if result.status == 'ok' %}
     {% if saved %}<p class="banner">Saved to <code>{{ saved }}</code></p>{% endif %}
     <h3>SQL</h3><pre>{{ result.sql }}</pre>
     <h3>YAML</h3><pre>{{ result.yml }}</pre>
   {% else %}<p>Rejected after retries - not written.</p>{% endif %}
 {% endif %}
{% endif %}
"""


@app.route("/", methods=["GET", "POST"])
def index():
    result, text, saved = None, "", None
    if request.method == "POST":
        text = request.form.get("request", "")
        if text.strip():
            result = generate(text, dry_run=DRY)
            # On a passing model, write the draft into the project's staging folder.
            if result.get("status") == "ok":
                GEN_DIR.mkdir(parents=True, exist_ok=True)
                name = result["name"]
                (GEN_DIR / f"{name}.sql").write_text(result["sql"] + "\n")
                (GEN_DIR / f"{name}.yml").write_text(result["yml"] + "\n")
                saved = f"generated/{name}.sql + generated/{name}.yml"
    return render_template_string(PAGE, result=result, request_text=text, dry=DRY, saved=saved)


if __name__ == "__main__":
    app.run(debug=True)
