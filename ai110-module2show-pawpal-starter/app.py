from datetime import date, time

import streamlit as st
from  pawpal_system import Task, Pet, Owner, Priority, Frequency, Scheduler

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
