"""The RAG orchestrator: knowledge base + LLM + PawPal+'s live schedule.

:class:`CareAdvisor` is the piece that makes this RAG rather than a document
search box. It assembles context from two very different sources:

1. **Static knowledge** — the ``knowledge/`` corpus, retrieved by
   :class:`care_kb.CareKnowledgeBase` (general pet care guidance)
2. **Live application state** — the owner's real ``Pet`` and ``Task`` objects
   from :mod:`pawpal_system` (this pet, this schedule, these conflicts)

Neither alone answers "when should I fit Buddy's walk in?" — the notes know
walks are 30-60 minutes and movable, only the scheduler knows 12:00 is already
double-booked.

Three answering modes, mirroring the DocuBot tinker activity:

- ``MODE_NAIVE``     — LLM only, no retrieval (the baseline to argue against)
- ``MODE_RETRIEVAL`` — retrieval only, no LLM (works with no API key)
- ``MODE_RAG``       — retrieval, then LLM grounded in what was retrieved
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from care_kb import REFUSAL, CareKnowledgeBase, Snippet, stem, tokenize
from pawpal_system import Owner, Scheduler

MODE_NAIVE = "naive"
MODE_RETRIEVAL = "retrieval"
MODE_RAG = "rag"

# Symptom and emergency words that mean the question is about a pet's health,
# not about scheduling. Stored stemmed so "vomiting" and "vomits" both match.
#
# This exists because keyword retrieval alone is unsafe here: "my cat is
# vomiting repeatedly, what is wrong?" retrieves FEEDING.md › Cats (it matches
# on "cat"), while the section that actually applies — VET_AND_SAFETY.md › Call
# a vet the same day — scores below the floor. A grounded answer built from the
# feeding notes would be worse than no answer at all.
SYMPTOM_TERMS = frozenset(
    stem(word)
    for word in """
    vomiting vomit throwing diarrhea diarrhoea bleeding blood seizure seizures
    collapse collapsed unconscious choking breathing panting limping limp
    lethargic lethargy swollen swelling poisoned poison toxic ate swallowed
    diagnose diagnosis symptom symptoms sick ill illness infection fever pain
    hurting injured injury wound emergency dying overdose
    """.split()
)

# Shown above any answer to a question containing a symptom term. Deliberately
# blunt: the owner should see this before they read anything else.
ESCALATION_BANNER = (
    "⚠️ **This sounds like a health question, not a scheduling one.** "
    "PawPal+ organises care tasks and cannot assess symptoms, diagnose, or "
    "advise on medication. Contact a veterinarian — same day for a symptom that "
    "is new or worsening, immediately for breathing trouble, collapse, "
    "seizures, or a suspected poison."
)

# Retrieval terms added when the escalation guard fires, so the vet and safety
# notes are surfaced even when the question's own words don't reach them.
ESCALATION_BOOSTS = ["veterinarian", "vet", "emergency", "safety"]

# The note file whose sections are pulled to the front of an escalated answer.
SAFETY_FILE = "VET_AND_SAFETY.md"

# Longest question accepted. Anything past this is almost certainly a paste, and
# a huge question both dilutes retrieval and inflates the prompt.
MAX_QUESTION_LENGTH = 500

# Raw retrieval strength treated as "fully confident" when normalising to
# 0.0-1.0. Calibrated against the 16 evaluation questions rather than guessed —
# the first value tried (8.0) pinned 8 of the 14 answerable questions at exactly
# 1.00, which makes the top of the scale meaningless. Measured saturation:
#
#     /8  -> 8 of 14 questions saturate, mean 0.87
#     /10 -> 4 saturate, mean 0.78
#     /12 -> 1 saturates, mean 0.68     <- chosen: widest usable spread
#
# Re-derive with: python rag_evaluation.py --confidence
CONFIDENCE_FULL_SCORE = 12.0

# Below this, the UI and CLI warn that the notes only weakly cover the question.
LOW_CONFIDENCE = 0.4

# Module logger. Handlers are attached by setup_logging() so importing this
# module never writes files as a side effect (tests import it constantly).
logger = logging.getLogger("pawpal")


def setup_logging(
    log_path: str = "pawpal.log",
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    """Send PawPal's log records to ``log_path`` (and warnings to the console).

    Called by the entry points (`app.py`, `ask_pawpal.py`), never on import, so
    the log is a property of *running the app* rather than of importing a module.
    Idempotent: Streamlit re-runs its script constantly and must not stack up a
    new handler every time.

    ``console=False`` keeps warnings out of stderr. The ``--demo`` transcript is
    markdown meant to be pasted into documentation, and interleaved log lines
    corrupt it — the records still reach the file either way.
    """
    if logger.handlers:
        return

    logger.setLevel(level)

    file_handler = logging.FileHandler(log_path, encoding="utf8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    )
    logger.addHandler(file_handler)

    if console:
        # Warnings and errors also go to the console, so a failure is visible
        # while you are using the app instead of only discoverable afterwards.
        stream = logging.StreamHandler()
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(stream)


@dataclass
class CareAnswer:
    """The result of one question, kept together with the evidence behind it.

    Returning the snippets alongside the text is deliberate: the UI shows them
    under the answer so an owner can check what the advice was based on, and
    :mod:`rag_evaluation` scores retrieval without re-running it.
    """

    question: str
    mode: str
    text: str
    snippets: List[Snippet] = field(default_factory=list)
    escalated: bool = False   # True when the vet-referral guardrail fired

    @property
    def sources(self) -> List[str]:
        """Return the citation labels of the snippets used, in rank order."""
        return [snippet.label for snippet in self.snippets]

    @property
    def confidence(self) -> float:
        """Return 0.0-1.0 for how well the notes actually cover this question.

        **This scores the retrieved evidence, not the model's belief.** It is a
        deliberate choice: asking a language model how sure it is produces a
        fluent number that does not track correctness, whereas retrieval strength
        is measurable and reproducible. Naming it honestly matters more than
        having an impressive-looking number.

        The formula is the top snippet's score plus a quarter of each supporting
        snippet's score (agreement across sections is weak corroboration),
        normalised by :data:`CONFIDENCE_FULL_SCORE` and clamped to 1.0. No
        snippets — a refusal, a rejected input, or naive mode — is 0.0, because
        there is genuinely no evidence behind the answer.

        Known distortion: because supporting snippets contribute, a question
        answered correctly by exactly one section scores low. "How often do nails
        need trimming?" retrieves the right section first and nothing else, and
        lands at 0.29. Read a low score as "check the sources", not as "wrong".
        """
        if not self.snippets:
            return 0.0

        top = self.snippets[0].score
        supporting = sum(s.score for s in self.snippets[1:])
        return min(1.0, (top + 0.25 * supporting) / CONFIDENCE_FULL_SCORE)

    @property
    def confidence_label(self) -> str:
        """Return ``high`` / ``medium`` / ``low`` / ``none`` for the confidence."""
        score = self.confidence
        if score == 0.0:
            return "none"
        if score < LOW_CONFIDENCE:
            return "low"
        return "medium" if score < 0.7 else "high"

    @property
    def body(self) -> str:
        """Return the answer without the escalation banner.

        ``text`` is the complete answer as a reader should see it, banner
        included. The UI wants to render the banner as its own alert block
        instead, so it needs the remainder on its own.
        """
        if self.escalated and self.text.startswith(ESCALATION_BANNER):
            return self.text[len(ESCALATION_BANNER):].lstrip()
        return self.text

    @property
    def is_refusal(self) -> bool:
        """Return True if the assistant declined to answer for lack of evidence.

        Checks :attr:`body`, not :attr:`text`: an escalated answer starts with
        the banner, which would otherwise mask the refusal underneath it and let
        the UI present "I do not know" as though it were a real answer.
        """
        return self.body.strip().startswith(REFUSAL)

    def __str__(self) -> str:
        """Return the answer text with its sources appended."""
        if not self.snippets:
            return self.text
        return f"{self.text}\n\nRetrieved from: {', '.join(self.sources)}"


class CareAdvisor:
    """Answers pet care questions using retrieved notes plus live schedule state."""

    def __init__(
        self,
        knowledge_base: Optional[CareKnowledgeBase] = None,
        llm_client=None,
    ) -> None:
        """Wire up the advisor.

        ``llm_client`` is optional on purpose: with no Gemini key the advisor is
        still fully usable in retrieval-only mode, exactly like DocuBot.
        """
        self.kb = knowledge_base or CareKnowledgeBase()
        self.llm_client = llm_client

    @property
    def has_llm(self) -> bool:
        """Return True if LLM-backed modes (naive, RAG) are available."""
        return self.llm_client is not None

    # --- query expansion --------------------------------------------------

    def expanded_terms(self, owner: Optional[Owner]) -> List[str]:
        """Return extra retrieval terms drawn from the owner's actual pets.

        Owners ask "how often should I feed her?" without saying "cat". The
        species, medication name, and pet names are added to the query so the
        cat section of FEEDING.md can win even though the word never appears in
        the question. This is cheap query expansion, and it is where knowing the
        application state pays off before the LLM is even involved.
        """
        if owner is None:
            return []

        terms: List[str] = []
        for pet in owner.pets:
            terms.append(pet.animal_type)
            terms.append(pet.name)
            if pet.needs_medication():
                terms.append("medication")
                terms.append(pet.medication or "")
        return [term for term in terms if term]

    # --- live application state as context --------------------------------

    def schedule_context(
        self,
        owner: Optional[Owner],
        scheduler: Optional[Scheduler] = None,
        max_tasks: int = 12,
    ) -> str:
        """Summarise the owner's pets and pending tasks as plain text.

        This is the second half of the context the LLM sees. It is built from
        the same objects the rest of the app uses, so the answer can never
        disagree with the schedule on screen.

        Only pending tasks are listed (completed chores are not decisions any
        more), capped at ``max_tasks`` so a busy household cannot balloon the
        prompt. Any conflict warning is included, since "two things at 12:00"
        is usually the real question behind "when should I do this?".
        """
        if owner is None or not owner.pets:
            return "No pets or tasks have been entered yet."

        lines = []
        for pet in owner.pets:
            meds = pet.medication if pet.needs_medication() else "none"
            lines.append(
                f"- Pet: {pet.name}, a {pet.animal_type}, "
                f"fed {pet.feeding_frequency}x/day, medication: {meds}"
            )

        # Prefer the scheduler's view when one is given: it holds the recurring
        # follow-up copies created by complete_task(), and it can sort.
        if scheduler is not None and scheduler.schedule:
            pending = [t for t in scheduler.organize_by_priority() if not t.completed]
        else:
            pending = owner.pending_tasks()

        if pending:
            lines.append(f"Pending tasks ({len(pending)}):")
            for task in pending[:max_tasks]:
                when = task.due_time.strftime("%H:%M") if task.due_time else "no time set"
                lines.append(
                    f"  - {task.description} — {when}, {task.duration} min, "
                    f"{task.frequency.name.lower()}, "
                    f"{task.priority_level.name.lower()} priority"
                )
            if len(pending) > max_tasks:
                lines.append(f"  - ...and {len(pending) - max_tasks} more")
        else:
            lines.append("No pending tasks.")

        if scheduler is not None:
            warning = scheduler.conflict_warning()
            if warning:
                lines.append(warning)

        return "\n".join(lines)

    # --- the three modes --------------------------------------------------

    def retrieve(
        self,
        question: str,
        owner: Optional[Owner] = None,
        top_k: int = 3,
    ) -> List[Snippet]:
        """Retrieve the snippets for ``question``, expanded with pet context."""
        escalate = self.is_health_question(question)
        boosts = self.expanded_terms(owner)
        if escalate:
            boosts = boosts + ESCALATION_BOOSTS

        snippets = self.kb.retrieve(question, top_k=top_k, boost_terms=boosts)

        if escalate:
            # Safety notes lead on a health question. Boosting alone isn't
            # enough: "my cat is vomiting" still scores FEEDING.md › Cats highest
            # (it matches "cat" in the heading), which is the wrong thing to read
            # first. Relative order within each group is preserved.
            snippets.sort(key=lambda s: s.source != SAFETY_FILE)

        return snippets

    # --- guardrails -------------------------------------------------------

    @staticmethod
    def is_health_question(question: str) -> bool:
        """Return True if ``question`` mentions a symptom, injury, or emergency.

        Stems the question and looks for any :data:`SYMPTOM_TERMS` word, so
        "vomiting", "vomits", and "vomited" all trip the guard.
        """
        return bool(set(tokenize(question)) & SYMPTOM_TERMS)

    @staticmethod
    def validate(question: str) -> Optional[str]:
        """Return an error message if ``question`` is unusable, else ``None``.

        Two cheap input checks that run before any retrieval or API call: empty
        input, and input long enough to be an accidental paste.
        """
        if not question:
            return "Ask a pet care question to get started."
        if len(question) > MAX_QUESTION_LENGTH:
            return (
                f"That question is {len(question)} characters long. "
                f"Please shorten it to under {MAX_QUESTION_LENGTH} and ask one "
                "thing at a time."
            )
        return None

    # --- asking -----------------------------------------------------------

    def ask(
        self,
        question: str,
        owner: Optional[Owner] = None,
        scheduler: Optional[Scheduler] = None,
        mode: str = MODE_RAG,
        top_k: int = 3,
    ) -> CareAnswer:
        """Answer ``question`` in the requested mode and return a :class:`CareAnswer`.

        Guardrails run in order, cheapest first:

        1. **Input validation** — empty or oversized questions are rejected
           before any work happens (:meth:`validate`).
        2. **Health escalation** — a symptom question gets a vet referral banner
           in *every* mode, including naive, because it is a property of the
           system rather than of one answering strategy
           (:meth:`is_health_question`).
        3. **Mode degradation** — an LLM mode with no API key falls back to
           retrieval-only instead of raising.
        4. **Evidence floor** — no retrieved snippets means refuse, without
           spending an API call.

        Every outcome is logged (see :func:`setup_logging`), including which guard
        fired and the confidence behind the answer, so a bad answer can be traced
        after the fact instead of reproduced by memory.
        """
        requested_mode = mode
        question = (question or "").strip()

        error = self.validate(question)
        if error:
            return self._logged(CareAnswer(question, mode, error), requested_mode)

        escalated = self.is_health_question(question)

        if mode in (MODE_NAIVE, MODE_RAG) and not self.has_llm:
            mode = MODE_RETRIEVAL

        if mode == MODE_NAIVE:
            # No retrieval at all: nothing grounds this answer, and no sources
            # can be reported for it. That absence is the point of the mode.
            # The banner still applies — an ungrounded answer to a symptom
            # question is the most dangerous output this system can produce.
            answer = CareAnswer(
                question, mode,
                self._with_banner(self.llm_client.naive_answer(question), escalated),
                escalated=escalated,
            )
            return self._logged(answer, requested_mode)

        snippets = self.retrieve(question, owner=owner, top_k=top_k)

        # Retrieval-only mode, and RAG with nothing retrieved, produce the same
        # thing: the snippets themselves (or the refusal when there are none).
        # RAG stops here rather than relying on the client to notice the empty
        # list — the rule belongs to the advisor, and it saves an API call.
        if mode == MODE_RETRIEVAL or not snippets:
            answer = CareAnswer(
                question, mode,
                self._with_banner(self._format_snippets(snippets), escalated),
                snippets, escalated,
            )
            return self._logged(answer, requested_mode)

        # MODE_RAG: retrieved evidence + live schedule -> grounded generation.
        text = self.llm_client.answer_from_snippets(
            question,
            snippets,
            schedule_context=self.schedule_context(owner, scheduler),
        )
        answer = CareAnswer(
            question, mode, self._with_banner(text, escalated), snippets, escalated
        )
        return self._logged(answer, requested_mode)

    @staticmethod
    def _logged(answer: CareAnswer, requested_mode: str) -> CareAnswer:
        """Log the outcome of one question, then return ``answer`` unchanged.

        One record per question, carrying the fields needed to explain a bad
        answer later: the mode actually used (and what was asked for, if they
        differ), which guardrail fired, the confidence, and the sources. Logged
        at WARNING when a guard fires so those lines also reach the console.
        """
        guard = "none"
        if answer.escalated:
            guard = "health-escalation"
        elif answer.is_refusal:
            guard = "refusal"
        elif not answer.snippets and answer.mode != MODE_NAIVE:
            guard = "input-validation"

        detail = (
            f"mode={answer.mode}"
            + (f" (requested {requested_mode})" if answer.mode != requested_mode else "")
            + f" guard={guard}"
            + f" confidence={answer.confidence:.2f} ({answer.confidence_label})"
            + f" sources=[{', '.join(answer.sources) or '-'}]"
            + f" q={answer.question[:80]!r}"
        )

        if guard == "none":
            logger.info(detail)
        else:
            logger.warning(detail)
        return answer

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _with_banner(text: str, escalated: bool) -> str:
        """Prefix ``text`` with the vet referral banner when escalation fired."""
        return f"{ESCALATION_BANNER}\n\n{text}" if escalated else text

    @staticmethod
    def _format_snippets(snippets: List[Snippet]) -> str:
        """Render snippets as readable text for retrieval-only mode.

        With nothing retrieved this returns the same refusal wording the RAG
        prompt uses, so both modes fail the same way from the user's side.
        """
        if not snippets:
            return (
                f"{REFUSAL} I have notes on feeding, medication, "
                "exercise, grooming, and vet visits."
            )
        return "\n\n---\n\n".join(str(snippet) for snippet in snippets)
