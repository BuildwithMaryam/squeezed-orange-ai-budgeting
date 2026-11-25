#!/usr/bin/env python3
"""Run every deterministic check (no network, no model calls), write evals/score.json and refresh the README score line.
Exit code 1 if any check fails, so it can gate a release or CI."""
import json, re, subprocess, sys, datetime
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parent.parent


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=PLUGIN)
    lines = [l for l in r.stdout.splitlines() if l.startswith(("PASS", "FAIL"))]
    return lines, r


def main():
    py, r1 = run([sys.executable, "tests/test_parse.py"])
    js, r2 = run(["node", "tests/test_dashboard.js"])
    allc = py + js
    passed = sum(l.startswith("PASS") for l in allc)
    total = len(allc)
    for l in allc:
        if l.startswith("FAIL"):
            print(l)
    score = {"date": datetime.date.today().isoformat(), "deterministic": {"passed": passed, "total": total,
             "areas": {"parsing and categorization": len(py), "dashboard logic": len(js)}},
             "modelGraded": "see evals/model-graded.json"}
    (PLUGIN / "evals").mkdir(exist_ok=True)
    (PLUGIN / "evals" / "score.json").write_text(json.dumps(score, indent=2) + "\n")
    mg = PLUGIN / "evals" / "model-graded.json"
    extra = ""
    if mg.exists():
        m = json.loads(mg.read_text())
        extra = f", plus {m['casesPassed']} of {m['casesTotal']} model-graded eval cases on {m['date']}"
    line = f"**Tested:** {passed} of {total} automated checks passing on {score['date']}{extra}. Details are in `evals/`."
    readme = REPO / "README.md"
    text = readme.read_text()
    block = f"<!-- eval-score:start -->\n{line}\n<!-- eval-score:end -->"
    if "<!-- eval-score:start -->" in text:
        text = re.sub(r"<!-- eval-score:start -->.*?<!-- eval-score:end -->", block, text, flags=re.S)
    else:
        text = text.replace("\n## ", f"\n{block}\n\n## ", 1) if "\n## " in text else text + "\n" + block + "\n"
    readme.write_text(text)
    print(f"{passed}/{total} checks passing")
    return 0 if passed == total and r1.returncode in (0, 1) and r2.returncode in (0, 1) else 1


if __name__ == "__main__":
    sys.exit(main())
