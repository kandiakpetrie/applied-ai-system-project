"""Tests for the PawPal+ RAG layer: knowledge base retrieval and the advisor.

Retrieval is pure Python, so it is tested directly. The LLM is replaced with a
:class:`FakeLLM` that records what it was asked — that way the tests assert on
the *contract* (was the answer grounded in retrieved snippets? was the live
schedule passed along?) without needing an API key or a network call.
"""

import logging
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care_advisor import (
    ESCALATION_BANNER,
    LOW_CONFIDENCE,
    MAX_QUESTION_LENGTH,
    MODE_NAIVE,
    MODE_RAG,
    MODE_RETRIEVAL,
    SAFETY_FILE,
    CareAdvisor,
    setup_logging,
)
from care_kb import REFUSAL, CareKnowledgeBase, stem, tokenize
from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task


class FakeLLM:
    """Stand-in for GeminiClient that records its calls instead of making them."""

    def __init__(self):
        self.naive_calls = []
        self.snippet_calls = []

    def naive_answer(self, question):
        self.naive_calls.append(question)
        return "naive answer"

    def answer_from_snippets(self, question, snippets, schedule_context=None):
        self.snippet_calls.append((question, list(snippets), schedule_context))
        return "grounded answer"


def make_owner():
    """Build an owner with one medicated cat and two pending tasks."""
    owner = Owner(
        name="Alice", birthday=date(1995, 3, 12), email="a@x.com", number="555"
    )
    mochi = Pet(
        name="Mochi",
        birthday=date(2021, 8, 1),
        animal_type="cat",
        feeding_frequency=3,
        medication="Thyroid tablet",
    )
    owner.add_pet(mochi)
    mochi.add_task(Task(
        description="Give Mochi medication",
        duration=2,
        frequency=Frequency.DAILY,
        priority_level=Priority.HIGH,
        due_date=date(2026, 7, 5),
        due_time=time(12, 0),
    ))
    mochi.add_task(Task(
        description="Feed Mochi (breakfast)",
        duration=5,
        frequency=Frequency.DAILY,
        priority_level=Priority.MEDIUM,
        due_date=date(2026, 7, 5),
        due_time=time(8, 0),
    ))
    return owner


# --- tokenizing and stemming ----------------------------------------------

def test_tokenize_drops_stopwords_and_punctuation():
    """Only meaning-bearing words survive tokenizing.

    "how", "should", "i", "a" and even "often" are stopwords — they appear in
    nearly every question, so they carry no signal about which note is relevant.
    """
    assert tokenize("How often should I bathe a dog?") == ["bath", "dog"]


def test_stem_folds_plurals_and_verb_forms():
    """Related spellings collapse to one stem so they match each other."""
    assert stem("cats") == stem("cat")
    assert stem("bathing") == stem("bathe")
    assert stem("doses") == stem("dose")
    assert stem("feeding") == stem("feeds") == stem("feed")


def test_stem_leaves_short_words_alone():
    """Length guards stop short words from being mangled into nothing."""
    assert stem("is") == "is"
    assert stem("has") == "has"


# --- knowledge base: loading and chunking ---------------------------------

def test_kb_loads_the_knowledge_corpus():
    """All five knowledge files load and produce chunks and an index."""
    kb = CareKnowledgeBase()

    assert len(kb.documents) == 5
    assert len(kb.chunks) > 20     # each file splits into several sections
    assert kb.index                # the inverted index is populated


def test_kb_chunks_by_heading():
    """Each chunk is one ## section, labelled with file and heading."""
    kb = CareKnowledgeBase()

    labels = [chunk.label for chunk in kb.chunks]

    assert "FEEDING.md › Cats" in labels
    assert "MEDICATION.md › Missed doses" in labels
    # A chunk holds its own section only, not the whole file.
    cats = next(c for c in kb.chunks if c.label == "FEEDING.md › Cats")
    assert "Adult cats" in cats.text
    assert "Puppies" not in cats.text


def test_kb_handles_missing_folder():
    """A missing knowledge folder degrades to empty, it does not raise."""
    kb = CareKnowledgeBase(knowledge_folder="no_such_folder")

    assert kb.documents == []
    assert kb.retrieve("how often should I feed my cat?") == []


# --- knowledge base: retrieval --------------------------------------------

def test_retrieve_finds_the_right_section():
    """A cat feeding question ranks the cat feeding section first."""
    kb = CareKnowledgeBase()

    top = kb.retrieve("How many times a day should I feed my cat?")[0]

    assert top.source == "FEEDING.md"
    assert top.heading == "Cats"


def test_retrieve_respects_top_k():
    """top_k caps how many snippets come back."""
    kb = CareKnowledgeBase()

    assert len(kb.retrieve("medication dose timing", top_k=2)) <= 2
    assert len(kb.retrieve("medication dose timing", top_k=5)) <= 5


def test_retrieve_orders_by_score_descending():
    """Results are ranked best-first."""
    kb = CareKnowledgeBase()

    scores = [s.score for s in kb.retrieve("how often do nails need trimming?", top_k=3)]

    assert scores == sorted(scores, reverse=True)


def test_retrieve_returns_nothing_for_off_topic_questions():
    """Out-of-corpus questions retrieve nothing, which forces a refusal."""
    kb = CareKnowledgeBase()

    assert kb.retrieve("What is the best pet insurance policy?") == []


def test_min_score_floor_is_what_rejects_weak_matches():
    """Dropping the floor lets thin one-word matches back in.

    Pins the floor's purpose: the off-topic question above is not unmatched, it
    is *weakly* matched, and MIN_SCORE is what keeps that out of the answer.
    """
    kb = CareKnowledgeBase()

    assert kb.retrieve("What is the best pet insurance policy?", min_score=0.5)


def test_boost_terms_add_context_the_question_lacks():
    """Species passed as a boost term brings in a section the words alone miss.

    "How often should I feed them?" names no animal, so the cat section is not
    retrieved at all until "cat" arrives from the application's own state.
    """
    kb = CareKnowledgeBase()
    question = "How often should I feed them?"

    without = kb.retrieve(question, top_k=4)
    with_boost = kb.retrieve(question, top_k=4, boost_terms=["cat"])

    assert not any(s.heading == "Cats" for s in without)
    assert any(s.heading == "Cats" for s in with_boost)


def test_boost_terms_do_not_outrank_the_question():
    """Context terms reorder results; they must not decide them.

    Regression test. At full weight, a household with two medicated pets pushed
    "Feeding around medication" above "Cats" for an explicit cat feeding
    question — the owner's own words lost to context they never typed.
    """
    kb = CareKnowledgeBase()
    household = ["dog", "cat", "Buddy", "Mochi", "medication",
                 "Heartworm prevention", "Thyroid tablet"]

    top = kb.retrieve("How many times a day should I feed my cat?",
                      top_k=1, boost_terms=household)[0]

    assert (top.source, top.heading) == ("FEEDING.md", "Cats")


def test_boost_terms_cannot_smuggle_in_off_topic_sections():
    """Expansion must not defeat the refusal guardrail.

    An off-topic question stays unanswerable even when a pet's whole profile is
    added as context — otherwise every question would retrieve *something*.
    """
    kb = CareKnowledgeBase()
    household = ["dog", "cat", "Buddy", "Mochi", "medication", "Thyroid tablet"]

    assert kb.retrieve("What is the best pet insurance policy?",
                       boost_terms=household) == []


# --- advisor: modes -------------------------------------------------------

def test_retrieval_only_mode_needs_no_llm():
    """Retrieval-only works with no LLM client at all."""
    advisor = CareAdvisor()          # no llm_client
    owner = make_owner()

    answer = advisor.ask("How often should I trim nails?", owner=owner, mode=MODE_RETRIEVAL)

    assert advisor.has_llm is False
    assert answer.snippets
    assert "GROOMING.md" in answer.sources[0]


def test_llm_modes_fall_back_to_retrieval_without_a_client():
    """Asking for RAG with no API key degrades instead of raising."""
    advisor = CareAdvisor()
    owner = make_owner()

    answer = advisor.ask("How often should I trim nails?", owner=owner, mode=MODE_RAG)

    assert answer.mode == MODE_RETRIEVAL


def test_rag_mode_grounds_the_llm_in_retrieved_snippets():
    """RAG hands the LLM the retrieved snippets and reports them as sources."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)
    owner = make_owner()

    answer = advisor.ask("What time should I give a twice daily medication?",
                         owner=owner, mode=MODE_RAG)

    assert answer.text == "grounded answer"
    question, snippets, _ = llm.snippet_calls[0]
    assert snippets == answer.snippets          # exactly what was retrieved
    assert any("MEDICATION.md" in s.label for s in snippets)


def test_rag_mode_passes_the_live_schedule_to_the_llm():
    """The prompt context includes the owner's real pets and pending tasks."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)
    owner = make_owner()
    scheduler = Scheduler()
    scheduler.build_schedule(owner)

    advisor.ask("When should I fit in a walk?", owner=owner,
                scheduler=scheduler, mode=MODE_RAG)

    _, _, context = llm.snippet_calls[0]
    assert "Mochi" in context
    assert "Give Mochi medication" in context
    assert "12:00" in context


def test_naive_mode_retrieves_nothing_and_cites_nothing():
    """The baseline mode has no evidence behind it — by design."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("How often should I feed my cat?", mode=MODE_NAIVE)

    assert answer.text == "naive answer"
    assert answer.snippets == []
    assert answer.sources == []
    assert llm.snippet_calls == []      # the knowledge base was never consulted


def test_rag_refuses_without_calling_the_llm_when_nothing_is_retrieved():
    """No evidence means refuse, and don't waste an API call doing it."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("What is the best pet insurance policy?", mode=MODE_RAG)

    assert answer.is_refusal
    assert answer.sources == []
    assert llm.snippet_calls == []      # no evidence -> no API call at all


# --- guardrail: health escalation ----------------------------------------

def test_symptom_question_triggers_the_vet_referral_banner():
    """A symptom question is escalated to a vet in every mode."""
    advisor = CareAdvisor()

    answer = advisor.ask("My cat is vomiting repeatedly, what is wrong?",
                         mode=MODE_RETRIEVAL)

    assert answer.escalated is True
    assert answer.text.startswith(ESCALATION_BANNER)


def test_escalation_puts_safety_notes_first():
    """Safety notes lead on a health question, ahead of higher-scoring sections.

    Regression test. "My cat is vomiting" scores FEEDING.md › Cats highest
    because "cat" is in that heading, so the owner's first line of reading would
    otherwise have been the feeding guide.
    """
    advisor = CareAdvisor()
    owner = make_owner()

    answer = advisor.ask("My cat is vomiting repeatedly, what is wrong?",
                         owner=owner, mode=MODE_RETRIEVAL)

    assert answer.snippets[0].source == SAFETY_FILE


def test_escalation_fires_in_naive_mode_too():
    """The banner is a system property, not a feature of one answering mode."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("My dog ate chocolate!", mode=MODE_NAIVE)

    assert answer.escalated is True
    assert answer.text.startswith(ESCALATION_BANNER)
    assert "naive answer" in answer.text     # the model still answered


def test_escalation_detects_word_variants():
    """Stemming means every form of a symptom word trips the guard."""
    advisor = CareAdvisor()

    assert advisor.is_health_question("she vomited twice")
    assert advisor.is_health_question("he is vomiting")
    assert advisor.is_health_question("my dog is limping")
    assert advisor.is_health_question("possible poisoning")


def test_ordinary_care_questions_are_not_escalated():
    """The guard must not cry wolf on routine scheduling questions."""
    advisor = CareAdvisor()

    for question in [
        "How often should I bathe a dog?",
        "How many times a day should I feed my cat?",
        "What time should I give a twice daily medication?",
        "When should I fit a walk in around my current tasks?",
    ]:
        answer = advisor.ask(question, mode=MODE_RETRIEVAL)
        assert answer.escalated is False, question
        assert not answer.text.startswith(ESCALATION_BANNER), question


def test_body_strips_the_banner_so_the_ui_can_render_it_separately():
    """`body` is the answer without the banner; `text` keeps it for the CLI."""
    advisor = CareAdvisor()

    answer = advisor.ask("My dog ate chocolate!", mode=MODE_RETRIEVAL)

    assert answer.text.startswith(ESCALATION_BANNER)
    assert not answer.body.startswith(ESCALATION_BANNER)
    assert answer.body                          # something is left underneath
    assert answer.body in answer.text


def test_escalated_refusal_is_still_reported_as_a_refusal():
    """A refusal under a banner must not read as a real answer.

    Regression test. `is_refusal` checked `text`, which starts with the banner
    once escalation fires, so an escalated "I do not know" reported False and the
    UI would have rendered it as though the notes had answered the question.
    """
    advisor = CareAdvisor()

    # Symptom wording (escalates) about an animal the corpus doesn't cover
    # (nothing clears the evidence floor).
    answer = advisor.ask("My iguana is lethargic and swollen, what is wrong?",
                         mode=MODE_RETRIEVAL)

    assert answer.escalated is True
    assert answer.snippets == []
    assert answer.is_refusal is True
    assert answer.body.startswith(REFUSAL)


# --- guardrail: input validation -----------------------------------------

def test_oversized_question_is_rejected_before_any_work():
    """A pasted wall of text is refused without retrieval or an API call."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("a" * (MAX_QUESTION_LENGTH + 1), mode=MODE_RAG)

    assert "shorten it" in answer.text
    assert answer.snippets == []
    assert llm.snippet_calls == []


def test_question_at_the_length_limit_is_accepted():
    """The limit is inclusive — exactly MAX_QUESTION_LENGTH is fine."""
    advisor = CareAdvisor()

    answer = advisor.ask("How often should I bathe a dog? ".ljust(MAX_QUESTION_LENGTH),
                         mode=MODE_RETRIEVAL)

    assert "shorten it" not in answer.text
    assert answer.snippets


def test_empty_question_is_handled():
    """Blank input gets a prompt to ask something, not a crash or an API call."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("   ", mode=MODE_RAG)

    assert llm.snippet_calls == []
    assert llm.naive_calls == []
    assert "Ask a pet care question" in answer.text


# --- advisor: schedule context -------------------------------------------

def test_schedule_context_lists_pets_and_pending_tasks():
    """The context summary names the pet, its meds, and each pending task."""
    advisor = CareAdvisor()
    owner = make_owner()

    context = advisor.schedule_context(owner)

    assert "Mochi" in context
    assert "cat" in context
    assert "Thyroid tablet" in context
    assert "Pending tasks (2)" in context


def test_schedule_context_omits_completed_tasks():
    """Finished chores are history, not scheduling decisions."""
    advisor = CareAdvisor()
    owner = make_owner()
    owner.all_tasks()[0].mark_complete()

    context = advisor.schedule_context(owner)

    assert "Pending tasks (1)" in context


def test_schedule_context_includes_conflict_warning():
    """A same-moment clash is surfaced to the LLM, since it drives the answer."""
    advisor = CareAdvisor()
    owner = make_owner()
    clash = Task(
        description="Feed Mochi (lunch)",
        duration=5,
        due_date=date(2026, 7, 5),
        due_time=time(12, 0),      # collides with the medication task
    )
    owner.pets[0].add_task(clash)
    scheduler = Scheduler()
    scheduler.build_schedule(owner)

    context = advisor.schedule_context(owner, scheduler)

    assert "conflict" in context.lower()


def test_schedule_context_handles_no_pets():
    """An empty app state produces a plain statement, not an error."""
    advisor = CareAdvisor()

    assert "No pets" in advisor.schedule_context(None)


def test_expanded_terms_come_from_the_owners_pets():
    """Query expansion pulls species, name, and medication out of app state."""
    advisor = CareAdvisor()
    owner = make_owner()

    terms = advisor.expanded_terms(owner)

    assert "cat" in terms
    assert "Mochi" in terms
    assert "medication" in terms


# --- confidence scoring ---------------------------------------------------

def test_confidence_is_zero_without_evidence():
    """A refusal has no evidence behind it, so it claims no confidence."""
    advisor = CareAdvisor()

    answer = advisor.ask("What is the best pet insurance policy?", mode=MODE_RETRIEVAL)

    assert answer.confidence == 0.0
    assert answer.confidence_label == "none"


def test_naive_mode_has_zero_confidence():
    """Naive mode retrieves nothing, so it cannot report confidence either."""
    llm = FakeLLM()
    advisor = CareAdvisor(llm_client=llm)

    answer = advisor.ask("How often should I feed my cat?", mode=MODE_NAIVE)

    assert answer.confidence == 0.0


def test_confidence_stays_in_range_across_all_sample_questions():
    """Confidence is always a usable 0.0-1.0, never negative or above 1."""
    advisor = CareAdvisor()

    for question in [
        "How many times a day should I feed my cat?",
        "When do I need to call a vet the same day?",   # the strongest match
        "How often do nails need trimming?",           # a single-source match
        "What is the best pet insurance policy?",       # no match
    ]:
        answer = advisor.ask(question, mode=MODE_RETRIEVAL)
        assert 0.0 <= answer.confidence <= 1.0, question


def test_stronger_evidence_scores_higher_confidence():
    """A question the notes cover well outscores one they barely cover."""
    advisor = CareAdvisor()

    strong = advisor.ask("How long should I walk an adult dog each day?",
                         mode=MODE_RETRIEVAL)
    weak = advisor.ask("How often do nails need trimming?", mode=MODE_RETRIEVAL)

    assert strong.confidence > weak.confidence


def test_confidence_labels_match_their_bands():
    """The label is a plain-language reading of the number."""
    advisor = CareAdvisor()

    answer = advisor.ask("How often do nails need trimming?", mode=MODE_RETRIEVAL)

    assert answer.confidence < LOW_CONFIDENCE
    assert answer.confidence_label == "low"


# --- logging --------------------------------------------------------------

def test_every_question_is_logged_with_its_outcome(caplog):
    """One record per question, carrying mode, guard, confidence, and sources."""
    advisor = CareAdvisor()

    with caplog.at_level(logging.INFO, logger="pawpal"):
        advisor.ask("How often should I bathe a dog?", mode=MODE_RETRIEVAL)

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "mode=retrieval" in message
    assert "guard=none" in message
    assert "confidence=" in message
    assert "GROOMING.md" in message


def test_guardrail_firings_are_logged_as_warnings(caplog):
    """A fired guard logs at WARNING so it also reaches the console."""
    advisor = CareAdvisor()

    with caplog.at_level(logging.INFO, logger="pawpal"):
        advisor.ask("My dog ate chocolate!", mode=MODE_RETRIEVAL)
        advisor.ask("What is the best pet insurance policy?", mode=MODE_RETRIEVAL)

    guards = [r.message for r in caplog.records]
    assert any("guard=health-escalation" in m for m in guards)
    assert any("guard=refusal" in m for m in guards)
    assert all(r.levelno == logging.WARNING for r in caplog.records)


def test_mode_degradation_is_recorded(caplog):
    """The log shows what was asked for when it differs from what ran."""
    advisor = CareAdvisor()      # no LLM client

    with caplog.at_level(logging.INFO, logger="pawpal"):
        advisor.ask("How often should I bathe a dog?", mode=MODE_RAG)

    assert "requested rag" in caplog.records[0].message


def test_setup_logging_is_idempotent(tmp_path):
    """Streamlit reruns the script constantly; handlers must not stack up."""
    logger = logging.getLogger("pawpal")
    saved = logger.handlers[:]
    logger.handlers = []
    try:
        log_file = tmp_path / "pawpal.log"
        setup_logging(str(log_file))
        first = len(logger.handlers)
        setup_logging(str(log_file))

        assert first > 0
        assert len(logger.handlers) == first
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = saved


# --- refusal wording is shared -------------------------------------------

def test_both_modes_refuse_with_the_same_wording():
    """Retrieval-only and RAG refuse identically, so the UI reads consistently."""
    advisor = CareAdvisor()

    answer = advisor.ask("What is the best pet insurance policy?", mode=MODE_RETRIEVAL)

    assert answer.text.startswith(REFUSAL)
    assert answer.is_refusal
