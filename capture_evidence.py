"""Regenerate every execution log quoted in the README.

Run it after any change that could move the numbers:

    python capture_evidence.py

It runs each documented command, writes the verbatim output to ``evidence/*.txt``
with the command recorded in a header, and prints a pass/fail summary. The README
quotes these files, so a grader can re-run this one command and diff the results
instead of taking the README's word for it.

Why a script rather than pasting terminal output by hand: hand-pasted numbers go
stale silently. Three of the figures in this project's docs were already stale
once (test counts after new tests landed), which is exactly the failure this
prevents.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent / "evidence"

# (filename, argv, note). Ordered so the log sample is captured last, after the
# demo run has actually written to pawpal.log.
COMMANDS = [
    (
        "tests.txt",
        [sys.executable, "-m", "pytest"],
        "Full automated test suite (scheduler + RAG layer).",
    ),
    (
        "evaluation.txt",
        [sys.executable, "rag_evaluation.py", "--quiet"],
        "Retrieval evaluation (both arms) plus the guardrail checks.",
    ),
    (
        "evaluation_verbose.txt",
        [sys.executable, "rag_evaluation.py"],
        "Same run with per-question retrieval detail.",
    ),
    (
        "confidence.txt",
        [sys.executable, "rag_evaluation.py", "--quiet", "--confidence"],
        "Confidence distribution across all sample questions.",
    ),
    (
        "demo_transcript.txt",
        [sys.executable, "ask_pawpal.py", "--demo"],
        "End-to-end advisor run over three fixed questions.",
    ),
    (
        "scheduler_demo.txt",
        [sys.executable, "main.py"],
        "Base-project scheduler demo (unchanged by this extension).",
    ),
    (
        "human_eval_sheet.txt",
        [sys.executable, "rag_evaluation.py", "--human-eval"],
        "Human review sheet, pre-populated with system behavior.",
    ),
]


def run(filename: str, argv: list, note: str) -> tuple:
    """Run one command, write its output to ``evidence/filename``, return status.

    stdout and stderr are merged so a traceback would be captured rather than
    silently lost, and the exit code is recorded in the file — a log that hides a
    failure is worse than no log.
    """
    result = subprocess.run(
        argv, cwd=Path(__file__).parent, capture_output=True, text=True
    )
    output = result.stdout + result.stderr

    header = [
        f"$ {' '.join('python' if a == sys.executable else a for a in argv)}",
        f"# {note}",
        f"# exit code: {result.returncode}",
        "-" * 70,
        "",
    ]
    (EVIDENCE_DIR / filename).write_text("\n".join(header) + output, encoding="utf8")
    return result.returncode, len(output.splitlines())


def main() -> int:
    EVIDENCE_DIR.mkdir(exist_ok=True)

    # Start the log fresh so the captured sample shows only this run. Otherwise
    # the tail mixes in records from older runs with stale confidence values,
    # which is worse than no sample — it looks current and isn't.
    log = Path(__file__).parent / "pawpal.log"
    log.unlink(missing_ok=True)

    print("Capturing execution evidence into evidence/\n")
    failures = 0

    for filename, argv, note in COMMANDS:
        code, lines = run(filename, argv, note)
        status = "ok" if code == 0 else f"FAILED (exit {code})"
        if code != 0:
            failures += 1
        print(f"  {filename:<26} {lines:>4} lines  {status}")

    # pawpal.log only exists once something has actually answered a question, so
    # copy it after the demo above has run.
    if log.exists():
        sample = log.read_text(encoding="utf8").splitlines()[-12:]
        (EVIDENCE_DIR / "pawpal_log_sample.txt").write_text(
            "# Tail of pawpal.log — one record per question asked.\n"
            "# Written automatically by care_advisor; guard firings log at WARNING.\n"
            + "-" * 70 + "\n\n"
            + "\n".join(sample) + "\n",
            encoding="utf8",
        )
        print(f"  {'pawpal_log_sample.txt':<26} {len(sample):>4} lines  ok")

    print(f"\n{len(COMMANDS)} command(s) captured, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
