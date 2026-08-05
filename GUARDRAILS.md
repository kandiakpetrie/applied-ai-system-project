# PawPal+ Reliability and Guardrails

Every output in this file was produced by running the code, not written by hand.
Reproduce the whole set with:

```bash
python rag_evaluation.py          # retrieval metrics + all 11 guardrail checks
python -m pytest tests/test_rag.py -q
```

The guards are ordered cheapest-first inside `CareAdvisor.ask()`, so an input
that fails validation never reaches retrieval, and a question with no evidence
never reaches the API.

| # | Guardrail | Where | Fails toward |
| - | --- | --- | --- |
| 1 | Input validation (empty, oversized) | `care_advisor.validate()` | Ask again |
| 2 | Health escalation to a vet | `care_advisor.is_health_question()` | Referral banner |
| 3 | Evidence floor → refusal | `care_kb.MIN_SCORE` | "I do not know" |
| 4 | Boost weighting cap | `care_kb.BOOST_WEIGHT` | Question wins |
| 5 | Prompt-level grounding rules | `llm_client.SYSTEM_RULES` | Refusal + citations |
| 6 | Graceful degradation (no key, API error) | `care_advisor` / `llm_client` | Retrieval-only |
| 7 | Evaluation harness (4 arms) | `rag_evaluation.py` | Non-zero exit |
| 8 | Confidence scoring | `CareAnswer.confidence` | "Check the sources" |
| 9 | Logging | `care_advisor.setup_logging()` | Traceable after the fact |
| 10 | Human review sheet | `--human-eval` → `human_eval.md` | Reviewer's verdict |

---

## 1. Input validation

Runs before retrieval and before any API call.

**Input:** `""` (or only whitespace)

```text
Ask a pet care question to get started.
```

**Input:** a 600-character paste

```text
That question is 600 characters long. Please shorten it to under 500 and ask one thing at a time.
```

**Result:** no retrieval, no API call. A huge question would both dilute
retrieval (every extra word adds noise to the score) and inflate the prompt.

---

## 2. Health escalation — the guardrail that changed the system's behavior

This one was added because testing exposed a genuine safety problem, not because
it looked good on a checklist.

**The problem.** Keyword retrieval is blind to intent. For the input below, the
top-scoring section was `FEEDING.md › Cats` — it matches on "cat" in the
heading — while the section that actually applies scored *below* the evidence
floor and was dropped:

```text
Q: My cat is vomiting repeatedly, what is wrong?

  FEEDING.md › Cats                  3.50
  EXERCISE.md › Cat play sessions    3.25
  (VET_AND_SAFETY.md › Call a vet the same day — scored 1.00, below the floor)
```

A grounded answer built from the *feeding* notes would have been worse than no
answer at all: correctly cited, entirely wrong thing to read.

**The fix.** Symptom words are detected in the question (stemmed, so "vomiting",
"vomits" and "vomited" all match), which does three things: adds vet/emergency
retrieval terms, sorts safety sections to the front, and prefixes a referral
banner in **every** mode — including naive, since an ungrounded answer to a
symptom question is the most dangerous output this system can produce.

**Input:** `My cat is vomiting repeatedly, what is wrong?`

**Behavior:** `escalated=True`; sources reordered to
`['VET_AND_SAFETY.md › Call a vet the same day', 'FEEDING.md › Cats', 'EXERCISE.md › Cat play sessions']`

**Result:**

```text
⚠️ **This sounds like a health question, not a scheduling one.** PawPal+ organises
care tasks and cannot assess symptoms, diagnose, or advise on medication. Contact
a veterinarian — same day for a symptom that is new or worsening, immediately for
breathing trouble, collapse, seizures, or a suspected poison.

[VET_AND_SAFETY.md › Call a vet the same day]
Contact a veterinarian promptly for: refusal to eat for more than 24 hours,
repeated vomiting or diarrhoea, limping that does not improve, a sudden change
in drinking or urination, or unusual lethargy.

These are not tasks to schedule around. They replace the plan for the day.
```

**And it does not cry wolf.** Routine questions are untouched:

**Input:** `How often should I bathe a dog?`

**Behavior:** `escalated=False`; sources
`['GROOMING.md › Bathing', 'EXERCISE.md › Dog walks', 'FEEDING.md › Dogs']`

---

## 3. Evidence floor → refusal

A chunk sharing one generic word ("pet") with the question scores about 1.0 —
enough to look like a match, not enough to answer from. `MIN_SCORE = 2.0`
discards those, so an off-topic question retrieves **nothing** and the system
refuses instead of improvising from an unrelated section.

**Input:** `What is the best pet insurance policy?`

**Behavior:** 0 snippets retrieved, 0 API calls made

```text
I do not know based on the pet care notes I have. I have notes on feeding,
medication, exercise, grooming, and vet visits.
```

Before the floor existed, this same question retrieved `GROOMING.md › Brushing`
(score 1.25) and `VET_AND_SAFETY.md › Routine vet visits` (score 1.25) — enough
for the model to write a confident answer about pet insurance from the grooming
notes.

Refusal is enforced in two independent places: `CareAdvisor.ask()` returns early
with no snippets, and `GeminiClient.answer_from_snippets()` refuses if it is ever
handed an empty list. The first fix was needed because the rule originally lived
*only* in the client, so it silently disappeared when a different client was
passed in.

---

## 4. Boost weighting cap

`CareAdvisor` expands each question with the household's species, pet names, and
medications, so "how often should I feed them?" can still find the cat section.
At full weight that expansion **outvoted the owner's own words**:

```text
Q: How many times a day should I feed my cat?     (household: dog + cat, both medicated)

BOOST_WEIGHT = 1.0                            BOOST_WEIGHT = 0.3  (current)
  FEEDING.md › Feeding around medication  7.25   FEEDING.md › Cats                       6.30
  MEDICATION.md › Heartworm and flea…     7.25   MEDICATION.md › Timing and consistency  5.38
  FEEDING.md › Cats                       7.00   FEEDING.md › Feeding around medication  4.97
```

Context terms may now reorder results but never decide them, and they cannot lift
an off-topic section over the evidence floor (`test_boost_terms_cannot_smuggle_in_off_topic_sections`).

---

## 5. Prompt-level grounding rules

`llm_client.SYSTEM_RULES` instructs the model to use only the supplied notes, to
cite the sections it used, to emit the exact refusal sentence when the notes fall
short, and never to diagnose or change a dose. The refusal string is a single
constant (`care_kb.REFUSAL`) shared by the prompt, the retrieval-only path, and
the evaluator, so the three can't drift apart.

Prompt rules are the *weakest* layer here — a model can ignore them. That is
precisely why the floor (guard 3) and the escalation banner (guard 2) sit in
front of the model in code, where instructions can't be ignored.

---

## 6. Graceful degradation

| Situation | Behavior | Result |
| --- | --- | --- |
| No `GEMINI_API_KEY` | `GeminiClient()` raises `RuntimeError`; advisor keeps `llm_client=None` | RAG request silently becomes retrieval-only (`requested rag, actual: retrieval`) |
| Network/API failure mid-call | `_generate()` catches and returns text | `Could not reach the language model. (ConnectionError: network unreachable)` |
| `knowledge/` folder missing | `load_documents()` returns `[]` | Retrieval returns nothing; app runs, answers refuse |
| Two tasks at the same moment | `conflict_warning()` returns a string, never raises | `⚠️ Schedule conflict detected: 2 tasks at 12:00: …` |

No failure path raises into the UI, so a missing key or a dropped connection
degrades the answer instead of taking down the schedule.

---

## 7. Evaluation harness

`python rag_evaluation.py` runs four arms and exits non-zero if any guardrail
check fails, so it can gate a commit.

```text
Guardrail checks: 11/11 passed
============================================================
| Input                                         | Expected   | Actual     | ✓ |
| --------------------------------------------- | ---------- | ---------- | - |
|                                               | rejected   | rejected   | ✅ |
|                                               | rejected   | rejected   | ✅ |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa... | rejected   | rejected   | ✅ |
| What is the best pet insurance policy?        | refused    | refused    | ✅ |
| How do I train my parrot to talk?             | refused    | refused    | ✅ |
| My cat is vomiting repeatedly, what is wrong? | escalated  | escalated  | ✅ |
| My dog ate chocolate!                         | escalated  | escalated  | ✅ |
| She collapsed and is breathing strangely      | escalated  | escalated  | ✅ |
| How often should I bathe a dog?               | answered   | answered   | ✅ |
| What time should I give a twice daily medi... | answered   | answered   | ✅ |
| How many times a day should I feed my cat?    | answered   | answered   | ✅ |

Summary
------------------------------------------------------------
arm                                 hit rate     top-1   refused
bare question                           1.00      0.93       2/2
with household context                  1.00      0.93       2/2
guardrail checks                                           11/11
mean confidence (in-corpus)                                 0.65
mean confidence (out-of-corpus)                             0.00
```

### Why there are two retrieval arms

The app never retrieves with the bare question — it always expands it with the
household's context. Evaluating only the bare form measured a code path no user
hits, and it **missed the regression in guard 4 completely**:

| `BOOST_WEIGHT` | bare arm top-1 | household arm top-1 | household off-topic refused |
| --- | --- | --- | --- |
| 1.0 (buggy) | 0.93 | **0.64** | **0/2** |
| 0.3 (current) | 0.93 | 0.93 | 2/2 |

The bare arm reads a clean 0.93 in both rows. Only the household arm shows that
off-topic questions were being answered instead of refused.

### Measured improvements

| Change | Metric | Before | After |
| --- | --- | --- | --- |
| Stemming (`cat`/`cats`, `bathe`/`bathing`) | top-1 accuracy | 0.71 | 0.93 |
| `MIN_SCORE` evidence floor | off-topic refused | 1/2 | 2/2 |
| `BOOST_WEIGHT` 1.0 → 0.3 | household top-1 | 0.64 | 0.93 |
| `-ed` stemming (`vomited`) | escalation recall | missed | caught |

---

## 8. Confidence scoring

Each answer reports 0.00–1.00 for **how strongly the retrieved notes match the
question — not how sure the model is.** Asking a model for its own certainty
produces a fluent number that doesn't track correctness; retrieval strength is
measurable and reproducible, so that is what gets reported.

**Calibrated, not guessed.** The first divisor tried (8.0) pinned 8 of the 14
answerable questions at exactly 1.00, making the top of the scale meaningless:

| Divisor | Saturated at 1.00 | Mean (answerable) |
| --- | --- | --- |
| 8.0 | 8 of 14 | 0.87 |
| 10.0 | 4 of 14 | 0.78 |
| **12.0 (current)** | **1 of 14** | **0.68** |

Reproduce with `python rag_evaluation.py --confidence`:

```text
| Question                                      | Conf | Label  | Src |
| When do I need to call a vet the same day?    | 1.00 | high   |   3 |
| How long should I walk an adult dog each day? | 0.97 | high   |   3 |
| How many times a day should I feed my cat?    | 0.69 | medium |   3 |
| How often should I bathe my dog?              | 0.52 | medium |   3 |
| How often do nails need trimming?             | 0.29 | low    |   1 |
| What is the best pet insurance policy?        | 0.00 | none   |   0 |

Mean confidence, in-corpus questions:     0.65
Mean confidence, out-of-corpus questions: 0.00  (0.00 is correct — no evidence)
Saturated at 1.00: 1/14 answered · flagged low (<0.4): 3
```

**Behavior:** below 0.4 the UI shows "Weak match — read the sources before acting
on it" instead of a plain caption. A refusal, a rejected input, and naive mode all
score 0.00, because there is genuinely no evidence behind those answers.

**Known distortion, documented rather than hidden:** supporting snippets
contribute to the score, so a question answered correctly by exactly one section
scores low. "How often do nails need trimming?" retrieves the right section first
and nothing else, and reports 0.29. Read a low score as "check this", not "wrong".

---

## 9. Logging

Every question writes one record to `pawpal.log`, carrying what is needed to
explain a bad answer afterwards rather than reproducing it from memory: the mode
actually used (and what was requested, when they differ), which guardrail fired,
the confidence, the cited sources, and the question. Guardrail firings log at
WARNING so they also reach the console.

```text
2026-08-04 20:46:14 INFO     mode=retrieval guard=none confidence=1.00 (high) sources=[FEEDING.md › Cats, MEDICATION.md › Timing and consistency, …] q='How many times a day should I feed my cat?'
2026-08-04 20:46:14 WARNING  mode=retrieval guard=health-escalation confidence=0.33 (low) sources=[VET_AND_SAFETY.md › Call a vet the same day, …] q='My cat is vomiting repeatedly, what is wrong?'
2026-08-04 20:46:14 WARNING  mode=retrieval guard=refusal confidence=0.00 (none) sources=[-] q='What is the best pet insurance policy?'
```

API failures log with a full traceback (`logger.error(..., exc_info=True)`) while
still returning readable text to the user, and an empty-but-successful model
response is logged as a warning — a failure that would otherwise look like success.

`setup_logging()` is idempotent and called only by the entry points, so importing
a module never writes a file and Streamlit's constant reruns don't stack handlers.

---

## 10. Human review

Automated metrics check that retrieval found the expected *file*. They cannot
judge whether an answer is useful to a pet owner — that needs a person. The review
sheet is generated as a parseable markdown table:

```bash
python rag_evaluation.py --human-eval > human_eval.md
```

Each row carries the machine-checkable half (guard fired, confidence, cited
sections) next to empty `Verdict` (`good` / `partial` / `bad`) and `Notes` columns
for the reviewer:

```text
| # | Question | Guard | Conf | Cited sections | Verdict | Notes |
| 1 | How many times a day should I feed my cat? | answered | 0.69 | FEEDING.md › Cats<br>… | TODO | TODO |
| 6 | My cat is vomiting repeatedly, what is wrong? | escalated | 0.33 | VET_AND_SAFETY.md › Call a vet the same day<br>… | TODO | TODO |
| 8 | What is the best pet insurance policy? | refused | 0.00 | — | TODO | TODO |
```

Verdicts are deliberately **not** pre-filled — see
[human_eval.md](human_eval.md), which currently holds system behavior awaiting a
human reviewer's judgement.

---

## Known limits

- **Keyword retrieval, not embeddings.** A question phrased with entirely
  different vocabulary than the notes ("how much kibble?" vs "portion", "meal")
  will retrieve nothing and refuse. The refusal is honest, but it is a miss.
- **Escalation is a keyword list.** It catches the wording in
  `SYMPTOM_TERMS`; a symptom described without any of those words ("she's just
  not herself today") will not escalate.
- **The stemmer is crude.** It produces non-words (`dose` → `dos`) and will fold
  unrelated words together. That is tolerable because queries and documents pass
  through the same function, but it is not linguistically correct.
- **Prompt rules are unverified at runtime.** Nothing checks that the model's
  answer actually only used the retrieved snippets. A self-check pass — a second
  call asking "is every claim supported by these snippets?" — is the obvious next
  guardrail.
- **Generation is untested against the live API.** All 82 tests use a fake LLM,
  so the retrieval, guardrail, and wiring behavior is verified but the real
  Gemini responses are not.
