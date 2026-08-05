"""CLI for the PawPal+ care advisor — the three RAG modes side by side.

Interactive::

    python ask_pawpal.py

Modes:
  1) Naive LLM      — no retrieval. Fluent and unsourced.
  2) Retrieval only — no LLM. Works with no API key.
  3) RAG            — retrieval + LLM, grounded and cited.
  4) Compare        — runs naive and RAG on the same question, back to back.

Mode 4 is the one worth running first: same question, one answer with sources
and one without, and it is usually obvious which you would act on.

Non-interactive, for pasting real output into the README::

    python ask_pawpal.py --demo

Runs a fixed set of questions through every available mode and prints a markdown
transcript. Same questions every time, so the output is reproducible.
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from datetime import date, time

from care_advisor import (
    MODE_NAIVE,
    MODE_RAG,
    MODE_RETRIEVAL,
    CareAdvisor,
    setup_logging,
)
from care_kb import CareKnowledgeBase
from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task

SAMPLE_QUESTIONS = [
    "How many times a day should I feed my cat?",
    "What time should I give a twice daily medication?",
    "I missed Mochi's dose this morning — what now?",
    "How often should I bathe a dog?",
    "When should I fit a walk in around my current tasks?",
    "What is the best pet insurance policy?",   # out of corpus -> should refuse
]


def build_demo_owner():
    """Build a small but realistic app state for the advisor to reason about.

    The advisor is only interesting when there is a real schedule to talk
    about, so this mirrors ``main.py``: two pets, medication, and a deliberate
    12:00 clash the assistant should notice.
    """
    owner = Owner(
        name="Alice",
        birthday=date(1995, 3, 12),
        email="alice@example.com",
        number="555-0100",
    )
    buddy = Pet(
        name="Buddy", birthday=date(2020, 5, 15), animal_type="dog",
        feeding_frequency=2, medication="Heartworm prevention",
    )
    mochi = Pet(
        name="Mochi", birthday=date(2021, 8, 1), animal_type="cat",
        feeding_frequency=3, medication="Thyroid tablet",
    )
    owner.add_pet(buddy)
    owner.add_pet(mochi)

    today = date(2026, 7, 5)
    buddy.add_task(Task("Feed Buddy", 5, Frequency.DAILY, Priority.HIGH,
                        due_date=today, due_time=time(7, 30)))
    buddy.add_task(Task("Walk Buddy", 30, Frequency.DAILY, Priority.MEDIUM,
                        due_date=today, due_time=time(17, 0)))
    mochi.add_task(Task("Feed Mochi (breakfast)", 5, Frequency.DAILY, Priority.MEDIUM,
                        due_date=today, due_time=time(8, 0)))
    mochi.add_task(Task("Give Mochi medication", 2, Frequency.DAILY, Priority.HIGH,
                        due_date=today, due_time=time(12, 0)))
    # Same moment as Mochi's dose -> a conflict the advisor sees in its context.
    buddy.add_task(Task("Give Buddy medication", 2, Frequency.MONTHLY, Priority.HIGH,
                        due_date=today, due_time=time(12, 0)))

    scheduler = Scheduler()
    scheduler.build_schedule(owner)
    return owner, scheduler


def try_create_llm_client(quiet=False):
    """Return ``(client, has_llm)``, degrading gracefully with no API key.

    ``quiet`` suppresses the warning so ``--demo`` output stays clean markdown.
    """
    try:
        from llm_client import GeminiClient

        return GeminiClient(), True
    except RuntimeError as exc:
        if not quiet:
            print("Warning: LLM modes are disabled.")
            print(f"Reason: {exc}\n")
        return None, False


def choose_question():
    """Let the user pick a sample question or type their own."""
    print("\nSample questions:")
    for i, question in enumerate(SAMPLE_QUESTIONS, start=1):
        print(f"  {i}) {question}")

    raw = input("\nPick a number, or type your own question: ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(SAMPLE_QUESTIONS):
        return SAMPLE_QUESTIONS[int(raw) - 1]
    return raw


def show(answer):
    """Print an answer with the snippets it was built from."""
    print("\n" + "-" * 60)
    print(f"Mode: {answer.mode}")
    print(f"Q: {answer.question}\n")
    print(answer.text)
    print(f"\nConfidence: {answer.confidence:.2f} ({answer.confidence_label}) "
          "— strength of the retrieved notes, not the model's certainty")
    if answer.snippets:
        print("Retrieved evidence:")
        for snippet in answer.snippets:
            print(f"  • {snippet.label}  (score {snippet.score:.2f})")
    else:
        print("Retrieved evidence: none")
    print("-" * 60)


# Questions used by --demo, chosen so one run exercises every outcome the system
# can produce: a clear in-corpus hit, one that needs the live schedule, one
# outside the notes (refusal), and one symptom question (vet escalation).
DEMO_QUESTIONS = [
    "How many times a day should I feed my cat?",
    "When should I fit a walk in around my current tasks?",
    "What is the best pet insurance policy?",
    "My cat is vomiting repeatedly, what is wrong?",
]


def run_demo(advisor, owner, scheduler):
    """Print a reproducible markdown transcript of the demo questions.

    Retrieval-only runs always; the LLM modes run only when a key is present, and
    say so plainly when it is not, so the transcript never implies output that
    was not actually produced.
    """
    print("# PawPal+ end-to-end demo transcript\n")
    print(f"Knowledge base: {advisor.kb}")
    print(f"Demo state: {owner}")
    print(f"LLM available: {'yes' if advisor.has_llm else 'no (GEMINI_API_KEY not set)'}\n")

    modes = [(MODE_RETRIEVAL, "Retrieval only (no LLM)")]
    if advisor.has_llm:
        modes.append((MODE_NAIVE, "Naive LLM (no retrieval)"))
        modes.append((MODE_RAG, "RAG (retrieval + LLM)"))

    for i, question in enumerate(DEMO_QUESTIONS, start=1):
        print(f"\n## Question {i}: {question}\n")

        for mode, label in modes:
            answer = advisor.ask(question, owner, scheduler, mode=mode)
            print(f"### {label}\n")
            print("```text")
            print(answer.text)
            print("```\n")
            print(f"**Confidence:** {answer.confidence:.2f} "
                  f"({answer.confidence_label})\n")
            if answer.snippets:
                sources = ", ".join(
                    f"{s.label} (score {s.score:.2f})" for s in answer.snippets
                )
                print(f"**Sources:** {sources}\n")
            else:
                print("**Sources:** none\n")

        if not advisor.has_llm:
            print("_Naive and RAG modes skipped: no `GEMINI_API_KEY` set._\n")


def main():
    demo = "--demo" in sys.argv
    # Every question this session lands in pawpal.log. In --demo the console
    # handler is off, so the emitted markdown stays clean enough to paste.
    setup_logging(console=not demo)

    if not demo:
        print("PawPal+ Care Advisor (RAG)")
        print("==========================\n")

    llm_client, has_llm = try_create_llm_client(quiet=demo)
    kb = CareKnowledgeBase()
    advisor = CareAdvisor(knowledge_base=kb, llm_client=llm_client)
    owner, scheduler = build_demo_owner()

    if demo:
        run_demo(advisor, owner, scheduler)
        return

    print(kb)
    print(f"Demo state → {owner}\n")

    while True:
        print("Choose a mode:")
        print(f"  1) Naive LLM (no retrieval){'' if has_llm else '  [unavailable: no API key]'}")
        print("  2) Retrieval only (no LLM)")
        print(f"  3) RAG (retrieval + LLM){'' if has_llm else '  [unavailable: no API key]'}")
        print(f"  4) Compare naive vs RAG{'' if has_llm else '  [unavailable: no API key]'}")
        print("  q) Quit")

        choice = input("Enter choice: ").strip().lower()

        if choice == "q":
            print("\nGoodbye.")
            break

        if choice not in {"1", "2", "3", "4"}:
            print("\nUnknown choice. Pick 1, 2, 3, 4, or q.\n")
            continue

        if choice in {"1", "3", "4"} and not has_llm:
            print("\nThat mode needs GEMINI_API_KEY. Try mode 2.\n")
            continue

        question = choose_question()
        if not question:
            print("\nNo question entered.\n")
            continue

        if choice == "1":
            show(advisor.ask(question, owner, scheduler, mode=MODE_NAIVE))
        elif choice == "2":
            show(advisor.ask(question, owner, scheduler, mode=MODE_RETRIEVAL))
        elif choice == "3":
            show(advisor.ask(question, owner, scheduler, mode=MODE_RAG))
        else:
            print("\n=== Without retrieval ===")
            show(advisor.ask(question, owner, scheduler, mode=MODE_NAIVE))
            print("\n=== With retrieval (RAG) ===")
            show(advisor.ask(question, owner, scheduler, mode=MODE_RAG))

        print()


if __name__ == "__main__":
    main()
