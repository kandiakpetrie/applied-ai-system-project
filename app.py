from datetime import date, time

from dotenv import load_dotenv

# Load GEMINI_API_KEY from .env before anything tries to construct an LLM client.
load_dotenv()

import streamlit as st
from  pawpal_system import Task, Pet, Owner, Priority, Frequency, Scheduler
from care_advisor import (
    ESCALATION_BANNER,
    LOW_CONFIDENCE,
    MODE_NAIVE,
    MODE_RAG,
    MODE_RETRIEVAL,
    CareAdvisor,
    setup_logging,
)
from care_kb import CareKnowledgeBase

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ app.

This Streamlit UI is wired up to the backend classes in `pawpal_system.py`:
it creates real **Owner**, **Pet**, and **Task** objects and uses the **Scheduler**
to build and order a care plan.

Use the inputs below as an interactive demo of the system.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

st.subheader("Quick Demo Inputs")

st.markdown("**Owner**")
owner_name = st.text_input("Owner name", value="Jordan")
owner_birthday = st.date_input("Owner birthday", value=date(2000, 1, 1))
owner_email = st.text_input("Owner email", value="jordan@example.com")
owner_number = st.text_input("Owner phone", value="555-0100")

st.markdown("**Pet**")
pet_name = st.text_input("Pet name", value="Mochi")
pet_birthday = st.date_input("Pet birthday", value=date(2020, 1, 1))
species = st.selectbox("Species", ["dog", "cat", "other"])
feeding_frequency = st.number_input(
    "Feeding frequency (times per day)", min_value=1, max_value=6, value=2
)
medication = st.text_input("Medication (leave blank if none)", value="")

# --- Wire Owner/Pet into the session "vault" -----------------------------
# st.reruns the whole script on every interaction, so we create the objects
# ONCE (guarded by `not in st.session_state`) and then just keep their
# attributes in sync with the inputs on every rerun.
if "owner" not in st.session_state:
    st.session_state.owner = Owner(
        name=owner_name,
        birthday=owner_birthday,
        email=owner_email,
        number=owner_number,
    )

if "pet" not in st.session_state:
    st.session_state.pet = Pet(
        name=pet_name,
        birthday=pet_birthday,
        animal_type=species,
        feeding_frequency=int(feeding_frequency),
    )
    # Attach the pet to the owner exactly once, when both are first created.
    st.session_state.owner.add_pet(st.session_state.pet)

# Grab the existing objects out of the vault to work with them.
owner = st.session_state.owner
pet = st.session_state.pet

# The Scheduler is the "brain" that organizes and manages tasks. Keep ONE in
# the vault so the same instance handles both completing tasks (recurring
# roll-forward) and generating the schedule below.
if "scheduler" not in st.session_state:
    st.session_state.scheduler = Scheduler()
scheduler = st.session_state.scheduler

# Update the attributes whenever the user changes the inputs. Because the
# script reruns top-to-bottom, assigning every run keeps them in sync while
# preserving everything else attached to the object (pets, tasks, etc.).
owner.name = owner_name
owner.birthday = owner_birthday
owner.email = owner_email
owner.number = owner_number

pet.name = pet_name
pet.birthday = pet_birthday
pet.animal_type = species
pet.feeding_frequency = int(feeding_frequency)
pet.medication = medication or None  # store None (not "") when left blank

st.caption(f"Owner in vault → {owner}")
st.caption(f"Pet in vault → {pet}")

# Surface the pet's medication status using the Pet's own helper.
if pet.needs_medication():
    st.caption(f"💊 {pet.name} needs medication: {pet.medication}")

st.markdown("### Tasks")
st.caption("Each task you add becomes a real Task object attached to the pet in the vault.")

# Map the friendly dropdown labels to the enum members the Task expects.
PRIORITY_OPTIONS = {"low": Priority.LOW, "medium": Priority.MEDIUM, "high": Priority.HIGH}
FREQUENCY_OPTIONS = {
    "once": Frequency.ONCE,
    "daily": Frequency.DAILY,
    "weekly": Frequency.WEEKLY,
    "monthly": Frequency.MONTHLY,
}

col1, col2, col3, col4 = st.columns(4)
with col1:
    task_title = st.text_input("Task title", value="Morning walk")
with col2:
    duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
with col3:
    priority = st.selectbox("Priority", list(PRIORITY_OPTIONS), index=2)
with col4:
    frequency = st.selectbox("Frequency", list(FREQUENCY_OPTIONS), index=1)

# A second row for WHEN the task is due. These feed the Scheduler's
# date/time sorting and its same-time conflict detection.
col5, col6 = st.columns(2)
with col5:
    due_date_in = st.date_input("Due date", value=date.today())
with col6:
    due_time_in = st.time_input("Due time", value=time(8, 0))

if st.button("Add task"):
    # Build a real Task (now with a due date/time) and attach it to the pet.
    task = Task(
        description=task_title,
        duration=int(duration),
        frequency=FREQUENCY_OPTIONS[frequency],
        priority_level=PRIORITY_OPTIONS[priority],
        due_date=due_date_in,
        due_time=due_time_in,
    )
    pet.add_task(task)

# Filter control — uses Owner.filter_tasks() to narrow what we display.
status_filter = st.radio(
    "Show", ["all", "pending", "completed"], horizontal=True, key="status_filter"
)
COMPLETED_ARG = {"all": None, "pending": False, "completed": True}
# filter_tasks(completed=None) means "no filter"; False/True are real filters.
visible_tasks = owner.filter_tasks(
    pet_name=pet.name, completed=COMPLETED_ARG[status_filter]
)

if visible_tasks:
    st.success(f"Showing {len(visible_tasks)} {status_filter} task(s) for {pet.name}.")
    # Keys use id(t), a stable per-object id, instead of the loop index — so
    # filtering or removing a task can't bind a widget to the wrong task.
    for t in visible_tasks:
        c_done, c_desc, c_meta, c_remove = st.columns([1, 4, 3, 1])
        with c_done:
            checked = st.checkbox(
                "done", value=t.completed, key=f"done_{id(t)}",
                label_visibility="collapsed",
            )
            if checked and not t.completed:
                # Delegate to the Scheduler: complete_task() marks the task done
                # and, for daily/weekly tasks, returns a fresh copy for the next
                # date. Attach that copy to the pet so it shows up in the list.
                follow_up = scheduler.complete_task(t)
                if follow_up is not None:
                    pet.add_task(follow_up)
                st.rerun()
            elif not checked and t.completed:
                t.mark_incomplete()
                st.rerun()
        with c_desc:
            recurring = " 🔁" if t.is_recurring() else ""
            when = f" · due {t.due_time.strftime('%H:%M')}" if t.due_time else ""
            st.write(f"**{t.description}**{recurring}{when}")
        with c_meta:
            st.caption(
                f"{t.duration} min · {t.frequency.name.lower()} · "
                f"priority {t.priority_level.name.lower()}"
            )
        with c_remove:
            if st.button("🗑", key=f"rm_{id(t)}", help="Remove this task"):
                pet.remove_task(t)
                st.rerun()
elif pet.tasks:
    st.info(f"No {status_filter} tasks to show. Try a different filter.")
else:
    st.info("No tasks yet. Add one above.")

st.divider()

st.subheader("Build Schedule")
st.caption("Generates a schedule from every task attached to the owner's pets.")

order_by = st.radio(
    "Order tasks by", ["priority", "date", "time"], horizontal=True
)

if st.button("Generate schedule"):
    # Reuse the vault's Scheduler; build_schedule() refreshes it from every
    # task currently attached to the owner's pets.
    scheduler.build_schedule(owner)  # pulls every task from all of the owner's pets

    # Each option maps to a different Scheduler sorting algorithm.
    if order_by == "priority":
        ordered = scheduler.organize_by_priority()   # priority, then time
    elif order_by == "date":
        ordered = scheduler.organize_by_date()        # full date + time
    else:
        ordered = scheduler.sort_by_time()            # time of day only

    if ordered:
        # Summary metrics give the plan a professional, dashboard-like header.
        pending_count = len(scheduler.pending_tasks())
        m1, m2, m3 = st.columns(3)
        m1.metric("Tasks", len(ordered))
        m2.metric("Pending", pending_count)
        m3.metric("Pending time", f"{scheduler.total_time()} min")

        st.caption(f"Schedule for {owner.name}, ordered by {order_by}.")

        # Render the sorted schedule as a clean table instead of a raw list.
        rows = []
        for i, task in enumerate(ordered, start=1):
            rows.append(
                {
                    "#": i,
                    "Status": "✓ Done" if task.completed else "○ Pending",
                    "Task": f"{'🔁 ' if task.is_recurring() else ''}{task.description}",
                    "Priority": task.priority_level.name.capitalize(),
                    "Duration": f"{task.duration} min",
                    "Frequency": task.frequency.name.capitalize(),
                    "Due date": task.due_date.strftime("%b %d, %Y") if task.due_date else "—",
                    "Time": task.due_time.strftime("%H:%M") if task.due_time else "—",
                }
            )
        st.table(rows)

        # Explain the plan: which task to do first and why.
        next_task = scheduler.next_task()
        if next_task:
            st.success(
                f"✅ Do this first: **{next_task.description}** "
                f"({next_task.priority_level.name.lower()} priority)"
            )

        # Lightweight conflict check — returns "" when clear, so this only
        # shows when two tasks are scheduled for the same moment.
        warning = scheduler.conflict_warning()
        if warning:
            st.warning(warning)
    else:
        st.info("No tasks to schedule yet. Add some tasks above.")

st.divider()

# =========================================================================
# Ask PawPal+ — Retrieval-Augmented Generation
# =========================================================================
# The scheduler above decides *when* things happen. This section answers *how*
# and *how often* questions, and it does so by retrieving from the knowledge/
# notes rather than letting the model answer from memory. Every answer either
# cites the sections it used or refuses.

st.subheader("💬 Ask PawPal+")
st.caption(
    "Answers come from the notes in `knowledge/` plus your live schedule above — "
    "not from the model's own memory."
)


@st.cache_resource
def load_knowledge_base():
    """Load and index the corpus once per session, not on every rerun.

    Streamlit reruns this whole script on every widget interaction, and reading
    plus indexing five files each time would be pure waste. cache_resource keeps
    one shared instance alive.
    """
    return CareKnowledgeBase()


@st.cache_resource
def load_llm_client():
    """Return a Gemini client, or None when GEMINI_API_KEY is not set.

    Returning None instead of raising is what lets the whole section still work
    in retrieval-only mode without a key.
    """
    try:
        from llm_client import GeminiClient

        return GeminiClient()
    except RuntimeError:
        return None


setup_logging()      # idempotent, so Streamlit's reruns don't stack handlers

kb = load_knowledge_base()
llm_client = load_llm_client()
advisor = CareAdvisor(knowledge_base=kb, llm_client=llm_client)

if not advisor.has_llm:
    st.info(
        "No `GEMINI_API_KEY` found, so **retrieval only** mode is available. "
        "Add a key to a `.env` file to enable RAG answers.",
        icon="🔑",
    )

MODE_LABELS = {
    "RAG (retrieval + LLM)": MODE_RAG,
    "Retrieval only (no LLM)": MODE_RETRIEVAL,
    "Naive LLM (no retrieval)": MODE_NAIVE,
}

col_q, col_mode = st.columns([3, 2])
with col_q:
    question = st.text_input(
        "Your question",
        value="What time should I give a twice daily medication?",
        key="rag_question",
    )
with col_mode:
    mode_label = st.selectbox("Answer mode", list(MODE_LABELS), key="rag_mode")

top_k = st.slider(
    "Snippets to retrieve (top-k)", min_value=1, max_value=6, value=3,
    help="How many note sections get pulled into the prompt as evidence.",
)

if st.button("Ask PawPal+", type="primary"):
    mode = MODE_LABELS[mode_label]

    # Pass the live objects: the advisor expands the query with this pet's
    # species/medication and summarises the pending tasks into the prompt.
    with st.spinner("Retrieving notes and composing an answer..."):
        answer = advisor.ask(question, owner=owner, scheduler=scheduler,
                             mode=mode, top_k=top_k)

    if answer.mode != mode:
        st.warning("That mode needs an API key — showing retrieval-only results.")

    # The vet referral gets its own alert block, above everything else. It is
    # rendered from answer.body below so the banner's markdown doesn't end up
    # shown literally inside the retrieval-mode code block.
    if answer.escalated:
        st.error(ESCALATION_BANNER, icon="⚠️")

    if answer.is_refusal:
        st.warning(answer.body, icon="🤷")
    elif answer.mode == MODE_RETRIEVAL:
        st.markdown("**Retrieved notes**")
        st.code(answer.body, language="markdown")
    else:
        st.markdown(answer.body)

    # Show the evidence. For naive mode there is none, and saying so plainly is
    # the most useful thing this section does.
    if answer.snippets:
        # Confidence scores the retrieved evidence, not the model's belief — a
        # low number means "the notes barely cover this", which is exactly when
        # a human should check the sources below before acting.
        conf_col, note_col = st.columns([1, 3])
        conf_col.metric("Confidence", f"{answer.confidence:.2f}",
                        answer.confidence_label)
        if answer.confidence < LOW_CONFIDENCE:
            note_col.warning(
                "Weak match — the notes only loosely cover this question. "
                "Read the sources below before acting on it.",
                icon="🔍",
            )
        else:
            note_col.caption(
                "Confidence reflects how strongly the retrieved notes match your "
                "question — not how sure the model is. Open the sources to check it."
            )

        st.caption(f"📚 Grounded in {len(answer.snippets)} note section(s)")
        for snippet in answer.snippets:
            with st.expander(f"{snippet.label}  ·  score {snippet.score:.2f}"):
                st.markdown(snippet.text)
    elif answer.mode == MODE_NAIVE:
        st.error(
            "⚠️ No sources: naive mode skips retrieval entirely, so nothing here "
            "is checked against your notes. Compare it with RAG mode.",
        )

with st.expander("What is RAG doing here?"):
    st.markdown(
        f"""
**Retrieve → Augment → Generate.**

1. **Retrieve** — your question is tokenized, stemmed, and matched against the
   {len(kb.chunks)} note sections in `knowledge/` via an inverted index. Each
   section is scored on word coverage, heading matches, and repetition; anything
   below the score floor is dropped so off-topic questions retrieve *nothing*.
2. **Augment** — the top-k sections are put in the prompt alongside a summary of
   your real pets and pending tasks, so the answer knows both general pet care
   guidance and what your day already looks like.
3. **Generate** — Gemini answers using only that context, cites the sections, and
   replies "I do not know based on the pet care notes I have" when the notes
   don't cover it.

Retrieval quality is measured separately with `python rag_evaluation.py`.
Currently loaded: {kb}
"""
    )
