# Model Card — PawPal+ Care Advisor

**System:** PawPal+ pet care scheduler with a Retrieval-Augmented Generation
advisor
**Base project:** PawPal+ (Module 2) — a scheduling system with no AI component
**Model:** Google `gemini-flash-lite-latest`, used only for generation over
retrieved text
**Retrieval:** local keyword search over 5 markdown notes (30 sections), no
embeddings, no external service
**Intended use:** helping a pet owner organise routine care tasks and look up
routine care guidance
**Out of scope:** diagnosis, dosing, emergency triage, or anything a
veterinarian should decide

---

## Limitations and Biases

**Retrieval is lexical, so vocabulary decides what gets found.** Matching is
keyword-based with a crude stemmer. An owner who asks "how much kibble should she
get?" retrieves nothing, because the notes say "portion" and "meal". The system
refuses honestly rather than guessing, but a refusal still reads to the user as
"this app doesn't know anything". A real fix is embedding-based retrieval.

**The corpus is small, hand-written, and reflects one author's assumptions.**
Five files covering feeding, medication, exercise, grooming, and vet basics. Its
biases are inherited directly by every answer:

- **Species bias.** Only dogs and cats are covered. A question about a rabbit,
  bird, or reptile either refuses or — worse — retrieves dog/cat guidance that
  looks authoritative and may be actively wrong for that animal.
- **Typical-adult-pet bias.** Guidance centres on healthy adult animals. Puppies
  and kittens get a line or two; seniors, disabled pets, and pets with chronic
  conditions are barely represented, so the system is least helpful for the
  animals needing the most care.
- **Regional and cultural bias.** Frequencies and norms ("a bath every four to
  six weeks", "an annual wellness exam") reflect Western, urban, veterinary-access
  assumptions and a household that can afford them.
- **Unsourced authority.** The notes carry no citations. They read authoritatively
  because they are formatted as documentation, not because they were reviewed by a
  vet.

**Confidence measures evidence, not correctness.** The score reflects how
strongly the retrieved notes match the question. It has a known distortion: a
question answered correctly by exactly one section scores low, because supporting
sections contribute to the number. "How often do nails need trimming?" retrieves
the right section first and still reports 0.29.

**The escalation guard is a keyword list.** It catches "vomiting", "limping",
"poison". It does not catch "she's just not herself today" — which is how owners
often describe the early signs that matter most. Coverage is measured (11/11
guardrail cases pass) but the case list is mine, so it measures the wording I
thought of.

**Nothing verifies the model's output at runtime.** The prompt instructs the
model to use only the retrieved notes and to cite them; no code checks that it
did. Of all the safeguards, the prompt rules are the only layer the model can
simply ignore.

**Generation is unverified against the live API.** All 85 tests substitute a fake
LLM. Retrieval, guardrails, logging, and wiring are proven; actual Gemini
responses are not.

---

## Misuse and Prevention

**The realistic misuse is not malicious — it is an owner treating this as a vet.**
Someone whose pet is unwell types the symptom into the nearest tool, gets a
confident, well-formatted, correctly-cited answer, and delays a call that should
have happened immediately. The system's own competence is what makes this
dangerous: sourced answers feel more trustworthy than a search engine's.

What prevents it, in the order it takes effect:

| Prevention | Where | Effect |
| --- | --- | --- |
| Symptom wording escalates to a vet | `care_advisor.is_health_question()` | Referral banner above the answer, in **every** mode |
| Safety notes are reordered first | `care_advisor.SAFETY_FILE` sort | The vet section is the first thing read |
| Prompt forbids diagnosis and dosing | `llm_client.SYSTEM_RULES` | Model instructed to redirect medical questions |
| Evidence floor | `care_kb.MIN_SCORE` | Off-topic questions refuse instead of improvising |
| Scope stated in the corpus itself | `knowledge/VET_AND_SAFETY.md` | The boundary is in the retrievable text, so it can be cited |

I deliberately put escalation in **code, before the model**, rather than trusting
the prompt. A prompt rule is a request; a keyword check that prepends a banner is
a guarantee. It also fires in naive mode, where there is no retrieval at all,
because an ungrounded answer to a symptom question is the worst output this system
can produce.

**A second misuse: over-trusting the citations.** An answer can cite a real
section and still be the wrong section — the vomiting case below did exactly that.
Mitigations are the confidence score, the source expanders in the UI (label and
score per snippet, so a mismatch is visible), and the log, which records the
sources behind every answer for after-the-fact review.

**What I would add before letting anyone else use it:** a self-check pass that
re-reads the generated answer against the snippets and refuses if a claim is
unsupported, and a vet review of the corpus before any of this guidance is shown
to a real owner.

---

## What Surprised Me While Testing Reliability

**1. A passing evaluation hid a real regression.** Query expansion (adding the
pet's species and medications to the query) was weighted the same as the owner's
own words. With two medicated pets, "How many times a day should I feed my cat?"
ranked *Feeding around medication* and *Heartworm and flea prevention* above
*Cats*. The eval reported a clean **0.93** top-1 the entire time — because it
called `retrieve()` with the bare question, **a code path the app never uses**.
Adding a second arm that evaluates questions the way the app actually issues them
exposed it immediately:

| `BOOST_WEIGHT` | bare arm top-1 | household arm top-1 | off-topic refused |
| --- | --- | --- | --- |
| 1.0 (buggy) | 0.93 | **0.64** | **0/2** |
| 0.3 (fixed) | 0.93 | 0.93 | 2/2 |

The lesson: a metric measured on a path nobody takes is worse than no metric,
because it buys false confidence.

**2. Correctly-cited answers can be dangerous.** Testing a symptom question
revealed that "My cat is vomiting repeatedly, what is wrong?" retrieved
`FEEDING.md › Cats` **first** — it matches "cat" in the heading — while
`VET_AND_SAFETY.md › Call a vet the same day` scored 1.00, *below the evidence
floor*, and was dropped entirely. Every safeguard I had built was working as
designed, and the result was a confident, sourced answer about feeding schedules
to an owner describing a sick animal. I had been treating "grounded" as a synonym
for "safe". It isn't. That produced the escalation guard.

**3. My own guardrail broke a different one.** After adding the escalation
banner, `is_refusal` silently started returning `False` for escalated answers,
because it checked whether the text *started with* the refusal sentence — and the
banner now came first. A symptom question about an animal the notes don't cover
("My iguana is lethargic and swollen") returned zero snippets with
`is_refusal=False`, so the UI would have presented "I do not know" as a real
answer. Safety features interact; each one needs its own regression test.

**4. Calibration needed data, not intuition.** My first confidence constant put
**8 of 14** answerable questions at exactly 1.00, making the top of the scale
meaningless. Measuring the distribution and picking a divisor that saturated once
took ten minutes and turned a decorative number into a useful one.

**5. Refusals are hard to earn.** Before the score floor, "What is the best pet
insurance policy?" retrieved the grooming section on the strength of the single
word "pet". Making a system say "I don't know" takes deliberate engineering; the
default behavior of every layer is to produce *something*.

---

## Collaboration With AI

I used Claude Code as a pair programmer for this extension, with the DocuBot
tinker activity as the structural reference (corpus → index → score → retrieve →
grounded prompt → eval). The prompts that worked were scoped to one piece —
"why does this question rank the exercise section above the feeding section?" —
rather than "build me RAG". The most valuable thing it pushed for was building the
evaluation harness *before* finishing retrieval, which is what made every
subsequent problem visible as a number instead of a hunch.

### One helpful suggestion

**Chunk the notes by `##` heading instead of retrieving whole files.** DocuBot
retrieves entire documents and my instinct was to copy that. Splitting each file
into sections meant a cat feeding question retrieves `FEEDING.md › Cats` — one
focused passage — rather than all 60 lines of the feeding guide, most of which is
about dogs. It improved ranking (less irrelevant text diluting the score),
shrank the prompt, and made citations specific enough to actually check. It also
turned out to be what made the confidence score possible, since per-section
scores are meaningful in a way per-file scores are not.

### One flawed suggestion

**Query expansion at full weight — described in detail in surprise #1 above.**
The idea was sound (owners say "them", not "cat"), but weighting context terms
equal to the owner's own words let a household's medications outvote an explicit
question about feeding. It shipped looking correct *and* with a green evaluation,
which is the worst combination. The fix was to discount boost terms to 0.3 and to
add the eval arm that would have caught it.

Two smaller flawed ones worth recording:

- The "refuse when there is no evidence" rule was originally placed **only**
  inside the Gemini client, so the guarantee silently disappeared when a
  different client was passed in. A test using a fake LLM caught it; the rule
  moved up into `CareAdvisor`, where it belongs.
- The stemmer folded `-ing` and `-s` but not `-ed`, so "vomited" never matched
  "vomiting" — a gap that mattered specifically because that word list drives the
  safety escalation.

### What I take from it

AI was strongest at structure and weakest at judgment about consequences. It
produced working retrieval quickly, and every failure it introduced was of the
same kind: locally reasonable, globally wrong, and invisible without a
measurement I had to insist on. The verification — the harness, the fake-LLM
tests, the guardrail cases — was where the real engineering was, and it was the
part I could not delegate.

---

## Human Evaluation

Automated metrics check that retrieval found the expected *file*; they cannot
judge whether an answer is useful to a pet owner. The review sheet is generated
in a parseable markdown table:

```bash
python rag_evaluation.py --human-eval > human_eval.md
```

It lists each question with the guard that fired, the confidence, and the cited
sections, leaving `Verdict` (`good` / `partial` / `bad`) and `Notes` for the
reviewer. See [human_eval.md](human_eval.md) — **verdicts are still to be filled
in by a human reviewer; the sheet ships pre-populated with system behavior only.**

---

## Reliability Summary

| Mechanism | Result |
| --- | --- |
| Automated tests | 85 passed, 0 failed (`pytest`) |
| Retrieval eval — bare question | hit rate 1.00, top-1 0.93, 2/2 off-topic refused |
| Retrieval eval — household context | hit rate 1.00, top-1 0.93, 2/2 off-topic refused |
| Guardrail checks | 11/11 passed (exits non-zero on failure) |
| Confidence, in-corpus questions | mean 0.65 (range 0.27–1.00) |
| Confidence, out-of-corpus questions | mean 0.00 — correct, no evidence exists |
| Logging | every question records mode, guard, confidence, sources; API errors log with traceback |
| Human evaluation | sheet generated; verdicts pending a reviewer |

Full input → behavior → result documentation: [GUARDRAILS.md](GUARDRAILS.md).
