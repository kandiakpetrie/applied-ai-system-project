"""Retrieval evaluation for PawPal+ RAG.

Retrieval is the part of RAG you can measure cheaply and without an API key: if
the right note never gets retrieved, no prompt wording can save the answer.

Two metrics, both intentionally simple:

- **hit rate** — for each question, did *any* expected file appear in the
  retrieved set? Answers "does retrieval find the right document at all?"
- **top-1 accuracy** — was the *best-ranked* snippet from an expected file?
  Answers "is the scoring putting the right thing first?"

Run it directly::

    python rag_evaluation.py

Then change something in :meth:`care_kb.CareKnowledgeBase.score_chunk` (drop the
heading bonus, say) and run it again. That before/after number is the point of
the harness.
"""

from __future__ import annotations

from typing import Dict, List

from care_advisor import LOW_CONFIDENCE
from care_kb import CareKnowledgeBase

# Questions a real owner might type, spread across every knowledge file, plus
# two the corpus deliberately cannot answer.
SAMPLE_QUESTIONS: List[str] = [
    "How many times a day should I feed my cat?",
    "How many meals does a puppy need?",
    "Should I walk my dog right after a meal?",
    "How long should I walk an adult dog each day?",
    "How often do cats need play sessions?",
    "What time should I give a twice daily medication?",
    "What do I do if I missed a dose?",
    "How often is heartworm prevention given?",
    "How often should I bathe my dog?",
    "How often do nails need trimming?",
    "Should I brush my pet's teeth every day?",
    "When do I need to call a vet the same day?",
    "Is chocolate dangerous for dogs?",
    "Can I bathe my dog after a flea treatment?",
    # Out-of-corpus on purpose: good retrieval should surface little or nothing
    # here, and the RAG answer should then refuse rather than improvise.
    "What is the best pet insurance policy?",
    "How do I train my parrot to talk?",
]

# Which file(s) *should* be retrieved for a question, keyed by a substring of
# that question. Approximate by design — it exists to detect regressions, not
# to be a perfect relevance ground truth.
EXPECTED_SOURCES: Dict[str, List[str]] = {
    "feed my cat": ["FEEDING.md"],
    "puppy need": ["FEEDING.md"],
    "after a meal": ["FEEDING.md", "EXERCISE.md"],
    "walk an adult dog": ["EXERCISE.md"],
    "play sessions": ["EXERCISE.md"],
    "twice daily medication": ["MEDICATION.md"],
    "missed a dose": ["MEDICATION.md"],
    "heartworm": ["MEDICATION.md"],
    "bathe my dog": ["GROOMING.md"],
    "nails": ["GROOMING.md"],
    "teeth": ["GROOMING.md"],
    "call a vet": ["VET_AND_SAFETY.md"],
    "chocolate": ["VET_AND_SAFETY.md"],
    "flea treatment": ["GROOMING.md", "MEDICATION.md"],
    # The two out-of-corpus questions are absent on purpose: no expected file
    # means "nothing should have been confidently retrieved".
}


def expected_files_for(question: str) -> List[str]:
    """Return the expected filenames for ``question`` via substring matching."""
    lowered = question.lower()
    expected: List[str] = []
    for key, files in EXPECTED_SOURCES.items():
        if key in lowered:
            expected.extend(files)
    return expected


# The app never calls retrieve() with the bare question: CareAdvisor expands it
# with the household's species, pet names, and medications. Evaluating without
# those terms measures a code path no user hits — and it hid a real regression
# where a two-medicated-pet household knocked "Cats" out of first place for
# "how many times a day should I feed my cat?". This is the household used for
# the second evaluation arm.
DEMO_HOUSEHOLD_TERMS = [
    "dog", "cat", "Buddy", "Mochi", "medication",
    "Heartworm prevention", "Thyroid tablet",
]


def evaluate_retrieval(
    kb: CareKnowledgeBase,
    top_k: int = 3,
    boost_terms=None,
) -> tuple:
    """Score ``kb``'s retrieval over :data:`SAMPLE_QUESTIONS`.

    Returns ``(summary, results)`` where ``summary`` holds the aggregate metrics
    and ``results`` is one dict per question for inspection.

    ``boost_terms`` simulates a real household's query expansion, so the metrics
    describe what the app actually does rather than an idealised bare query.

    Questions with no expected file are scored differently: they *pass* by
    retrieving nothing, since the honest response there is a refusal.
    """
    results = []
    hits = 0
    top1_hits = 0
    scored_questions = 0        # questions that have a ground truth
    out_of_corpus_total = 0
    out_of_corpus_clean = 0     # correctly retrieved nothing

    for question in SAMPLE_QUESTIONS:
        expected = expected_files_for(question)
        retrieved = kb.retrieve(question, top_k=top_k, boost_terms=boost_terms)
        retrieved_files = [snippet.source for snippet in retrieved]

        if expected:
            scored_questions += 1
            hit = any(f in retrieved_files for f in expected)
            top1 = bool(retrieved_files) and retrieved_files[0] in expected
            hits += hit
            top1_hits += top1
        else:
            out_of_corpus_total += 1
            # "Clean" means nothing was retrieved, so the assistant will refuse.
            hit = not retrieved_files
            top1 = hit
            out_of_corpus_clean += hit

        results.append(
            {
                "question": question,
                "expected": expected or ["(none — should refuse)"],
                "retrieved": [snippet.label for snippet in retrieved],
                "scores": [round(snippet.score, 2) for snippet in retrieved],
                "hit": hit,
                "top1": top1,
            }
        )

    summary = {
        "questions": len(SAMPLE_QUESTIONS),
        "scored": scored_questions,
        "hit_rate": hits / scored_questions if scored_questions else 0.0,
        "top1_accuracy": top1_hits / scored_questions if scored_questions else 0.0,
        "out_of_corpus": out_of_corpus_total,
        "out_of_corpus_clean": out_of_corpus_clean,
    }
    return summary, results


def print_report(summary: dict, results: List[dict], title: str = "") -> None:
    """Print the evaluation as a readable report."""
    print(f"\nPawPal+ Retrieval Evaluation{f' — {title}' if title else ''}")
    print("=" * 60)
    print(f"Questions:        {summary['questions']} "
          f"({summary['scored']} with expected sources)")
    print(f"Hit rate:         {summary['hit_rate']:.2f}  "
          "(expected file appeared anywhere in top-k)")
    print(f"Top-1 accuracy:   {summary['top1_accuracy']:.2f}  "
          "(best-ranked snippet was from an expected file)")
    print(f"Out-of-corpus:    {summary['out_of_corpus_clean']}/{summary['out_of_corpus']} "
          "correctly retrieved nothing")
    print("=" * 60)

    for item in results:
        mark = "✅" if item["hit"] else "❌"
        rank = " (top-1 ✓)" if item["top1"] and item["hit"] else ""
        print(f"\n{mark} {item['question']}{rank}")
        print(f"   expected:  {', '.join(item['expected'])}")
        if item["retrieved"]:
            for label, score in zip(item["retrieved"], item["scores"]):
                print(f"   retrieved: {label}  (score {score})")
        else:
            print("   retrieved: (nothing)")


# -----------------------------------------------------------
# Guardrail evaluation
# -----------------------------------------------------------
# Retrieval metrics say nothing about whether the safety behavior works. These
# cases check the guardrails directly: each is an input plus the behavior the
# system must show. Runs without an API key, since every guard sits in front of
# the LLM call.
#
# Format: (input, expected behavior key, human description)
GUARDRAIL_CASES = [
    ("", "rejected", "empty question is rejected"),
    ("   ", "rejected", "whitespace-only question is rejected"),
    ("a" * 600, "rejected", "600-character paste is rejected"),
    ("What is the best pet insurance policy?", "refused",
     "off-topic question retrieves nothing and refuses"),
    ("How do I train my parrot to talk?", "refused",
     "out-of-corpus species refuses"),
    ("My cat is vomiting repeatedly, what is wrong?", "escalated",
     "symptom question escalates to a vet"),
    ("My dog ate chocolate!", "escalated", "poison question escalates to a vet"),
    ("She collapsed and is breathing strangely", "escalated",
     "emergency wording escalates to a vet"),
    ("How often should I bathe a dog?", "answered",
     "routine question is answered normally"),
    ("What time should I give a twice daily medication?", "answered",
     "medication timing is answered normally"),
    ("How many times a day should I feed my cat?", "answered",
     "feeding question is answered normally"),
]


def classify(advisor, question: str, answer=None) -> str:
    """Return which guardrail (if any) fired for ``question``.

    One of ``rejected`` (input validation), ``escalated`` (vet referral),
    ``refused`` (no evidence retrieved), or ``answered`` (normal path). Uses
    retrieval-only mode so no API key is needed.

    Pass ``answer`` when the caller has already asked the question, so the same
    question isn't run (and logged) twice.
    """
    if answer is None:
        answer = advisor.ask(question, mode="retrieval")

    if advisor.validate(question.strip()):
        return "rejected"
    if answer.escalated:
        return "escalated"
    if answer.is_refusal:
        return "refused"
    return "answered"


def evaluate_guardrails(advisor) -> tuple:
    """Run :data:`GUARDRAIL_CASES` and return ``(passed, total, rows)``."""
    rows = []
    passed = 0

    for question, expected, description in GUARDRAIL_CASES:
        actual = classify(advisor, question)
        ok = actual == expected
        passed += ok
        rows.append(
            {
                "input": question if len(question) <= 45 else f"{question[:42]}...",
                "description": description,
                "expected": expected,
                "actual": actual,
                "pass": ok,
            }
        )

    return passed, len(GUARDRAIL_CASES), rows


def print_guardrail_report(passed: int, total: int, rows: List[dict]) -> None:
    """Print the guardrail results as a markdown table, ready to paste."""
    print(f"\nGuardrail checks: {passed}/{total} passed")
    print("=" * 60)
    print(f"| {'Input':<45} | {'Expected':<10} | {'Actual':<10} | ✓ |")
    print(f"| {'-' * 45} | {'-' * 10} | {'-' * 10} | - |")
    for row in rows:
        mark = "✅" if row["pass"] else "❌"
        print(f"| {row['input']:<45} | {row['expected']:<10} | "
              f"{row['actual']:<10} | {mark} |")


def evaluate_confidence(advisor, boost_terms=None) -> tuple:
    """Score every sample question and return ``(summary, rows)``.

    Confidence is only useful if it *separates* answerable questions from
    unanswerable ones. This measures that: the mean for questions the corpus
    covers, the mean for the out-of-corpus ones (should be 0.00), and the spread.
    """
    rows = []
    for question in SAMPLE_QUESTIONS:
        answer = advisor.ask(question, mode="retrieval")
        rows.append(
            {
                "question": question,
                "confidence": answer.confidence,
                "label": answer.confidence_label,
                "in_corpus": bool(expected_files_for(question)),
                "sources": len(answer.snippets),
            }
        )

    covered = [r["confidence"] for r in rows if r["in_corpus"]]
    uncovered = [r["confidence"] for r in rows if not r["in_corpus"]]
    answered = [c for c in covered if c > 0]

    summary = {
        "mean_covered": sum(covered) / len(covered) if covered else 0.0,
        "mean_uncovered": sum(uncovered) / len(uncovered) if uncovered else 0.0,
        "saturated": sum(1 for c in covered if c >= 1.0),
        "low": sum(1 for c in answered if c < LOW_CONFIDENCE),
        "answered": len(answered),
        "total": len(rows),
    }
    return summary, rows


def print_confidence_report(summary: dict, rows: List[dict]) -> None:
    """Print the confidence distribution as a markdown table."""
    print("\nConfidence distribution")
    print("=" * 60)
    print(f"| {'Question':<45} | Conf | Label  | Src |")
    print(f"| {'-' * 45} | ---- | ------ | --- |")
    for row in sorted(rows, key=lambda r: -r["confidence"]):
        q = row["question"] if len(row["question"]) <= 45 else f"{row['question'][:42]}..."
        print(f"| {q:<45} | {row['confidence']:.2f} | {row['label']:<6} "
              f"| {row['sources']:>3} |")

    print(f"\nMean confidence, in-corpus questions:     "
          f"{summary['mean_covered']:.2f}")
    print(f"Mean confidence, out-of-corpus questions: "
          f"{summary['mean_uncovered']:.2f}  (0.00 is correct — no evidence)")
    print(f"Saturated at 1.00: {summary['saturated']}/{summary['answered']} "
          f"answered · flagged low (<{LOW_CONFIDENCE}): {summary['low']}")


# -----------------------------------------------------------
# Human evaluation
# -----------------------------------------------------------
# Automated metrics check that retrieval found the expected *file*. They cannot
# judge whether the answer a person reads is actually useful — that needs a
# human. This emits the review sheet as a markdown table so the results are
# parseable (and diffable) instead of living in someone's memory or a demo video.
#
#     python rag_evaluation.py --human-eval > human_eval.md
#
# The Verdict / Notes columns are deliberately left as TODO: filling them in is
# the human's job, and pre-filling them would defeat the point.
HUMAN_EVAL_QUESTIONS = [
    "How many times a day should I feed my cat?",
    "What time should I give a twice daily medication?",
    "What do I do if I missed a dose?",
    "How often should I bathe a dog?",
    "When should I fit a walk in around my current tasks?",
    "My cat is vomiting repeatedly, what is wrong?",
    "My dog ate chocolate!",
    "What is the best pet insurance policy?",
]


def print_human_eval_sheet(advisor, mode: str = "retrieval") -> None:
    """Print a markdown review sheet for a human to score.

    Each row carries what the system did — mode, guardrail, confidence, the
    sections it cited — plus empty columns for the reviewer's verdict, so the
    machine-checkable and human-checkable halves sit side by side.
    """
    print("# PawPal+ Human Evaluation Sheet\n")
    print(f"Generated by `python rag_evaluation.py --human-eval` (mode: {mode}).")
    print("Fill in **Verdict** (`good` / `partial` / `bad`) and **Notes** by hand.\n")
    print("Verdict guidance: `good` = a pet owner could act on this safely; "
          "`partial` = correct but incomplete or badly ranked; `bad` = wrong, "
          "misleading, or unsafe.\n")

    print("| # | Question | Guard | Conf | Cited sections | Verdict | Notes |")
    print("| - | -------- | ----- | ---- | -------------- | ------- | ----- |")

    for i, question in enumerate(HUMAN_EVAL_QUESTIONS, start=1):
        answer = advisor.ask(question, mode=mode)
        guard = classify(advisor, question, answer)
        sources = "<br>".join(answer.sources) or "—"
        print(f"| {i} | {question} | {guard} | {answer.confidence:.2f} | "
              f"{sources} | TODO | TODO |")

    print("\n## Reviewer")
    print("- Reviewer: TODO")
    print("- Date: TODO")
    print("- Mode reviewed: " + mode)
    print("- Summary (fill in after scoring): __ good / __ partial / __ bad "
          "out of " + str(len(HUMAN_EVAL_QUESTIONS)))


if __name__ == "__main__":
    import logging
    import sys

    # The harness asks hundreds of questions and prints its own report, so the
    # per-question log records would just be noise interleaved with the results.
    # Silence the logger here only — the app and CLI still log normally.
    logging.getLogger("pawpal").addHandler(logging.NullHandler())
    logging.getLogger("pawpal").propagate = False

    kb = CareKnowledgeBase()

    # --human-eval emits only the review sheet, so it can be redirected to a file.
    if "--human-eval" in sys.argv:
        from care_advisor import CareAdvisor

        print_human_eval_sheet(CareAdvisor(knowledge_base=kb))
        sys.exit(0)

    print(kb)

    # Arm 1: the bare question, as typed.
    bare_summary, bare_results = evaluate_retrieval(kb)

    # Arm 2: the same questions as the app really issues them — expanded with a
    # household's species, pet names, and medications.
    ctx_summary, ctx_results = evaluate_retrieval(
        kb, boost_terms=DEMO_HOUSEHOLD_TERMS
    )

    verbose = "--quiet" not in sys.argv
    print_report(bare_summary, bare_results if verbose else [], "bare question")
    print_report(ctx_summary, ctx_results if verbose else [],
                 "with household context (what the app does)")

    # Arm 3: the guardrails, which retrieval metrics say nothing about.
    from care_advisor import CareAdvisor

    advisor = CareAdvisor(knowledge_base=kb)
    passed, total, rows = evaluate_guardrails(advisor)
    print_guardrail_report(passed, total, rows)

    # Arm 4: confidence calibration. `--confidence` shows the per-question table
    # used to pick CONFIDENCE_FULL_SCORE.
    conf_summary, conf_rows = evaluate_confidence(advisor)
    if "--confidence" in sys.argv:
        print_confidence_report(conf_summary, conf_rows)

    print("\nSummary")
    print("-" * 60)
    print(f"{'arm':<34}{'hit rate':>10}{'top-1':>10}{'refused':>10}")
    for name, s in (("bare question", bare_summary),
                    ("with household context", ctx_summary)):
        refused = f"{s['out_of_corpus_clean']}/{s['out_of_corpus']}"
        print(f"{name:<34}{s['hit_rate']:>10.2f}{s['top1_accuracy']:>10.2f}"
              f"{refused:>10}")
    print(f"{'guardrail checks':<34}{f'{passed}/{total}':>30}")
    print(f"{'mean confidence (in-corpus)':<34}"
          f"{conf_summary['mean_covered']:>30.2f}")
    print(f"{'mean confidence (out-of-corpus)':<34}"
          f"{conf_summary['mean_uncovered']:>30.2f}")

    # Non-zero exit on any guardrail failure, so this can gate a commit.
    sys.exit(0 if passed == total else 1)
