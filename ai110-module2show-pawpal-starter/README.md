# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## 🖥️ Sample Output

Paste a sample of your app's CLI or Streamlit output here so a reader can see what a generated plan looks like:

=== Today's Schedule ===
  [✗] Feed Buddy (5 min, daily, priority high, due 07:30)
  [✗] Give Mochi medication (2 min, daily, priority high, due 12:00)
  [✗] Walk Buddy (30 min, daily, priority medium, due 17:00)

Total time needed: 37 minutes
Up next (most urgent): Feed Buddy

```
# e.g.:
# Daily plan for Biscuit (Golden Retriever):
#   08:00 — Morning walk (30 min) [priority: high]
#   09:00 — Feeding (10 min) [priority: high]
#   ...
```

## 🧪 Testing PawPal+

```bash
# Run the full test suite:
pytest

# Run with coverage:
pytest --cov
```

Sample test output:

```
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/kandiakpetrie/CodePath/ai110-module2show-pawpal-starter
plugins: anyio-4.13.0
collected 37 items

test_pawpal.py ..                                                        [  5%]
tests/test_pawpal.py ...................................                 [100%]

============================== 37 passed in 0.08s ==============================

```

## 📐 Smarter Scheduling

> Fill in once you've implemented scheduling logic.

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | Scheduler.organize_by_priority(), Scheduler.organize_by_date(), Scheduler.sort_by_time() | The scheduler can organize tasks in three different ways: by priority, by date, or by time. Priority puts high-priority tasks first, date sorts from the earliest due date, and time orders tasks by the time of day. Tasks without a date or time are pushed to the end. |
| Filtering | Owner.filter_tasks(), Owner.pending_tasks(), Pet.pending_tasks() | Users can filter tasks by pet or by whether they're completed or still pending. The app can show all tasks, only completed ones, or only the ones that still need to be done.|
| Conflict handling | Scheduler.find_conflicts(), Scheduler.has_conflicts(), Scheduler.conflict_warning() | The scheduler checks if two or more pending tasks are scheduled for the exact same date and time. If it finds a conflict, it gives a warning instead of crashing so the user knows they need to adjust the schedule.|
| Recurring tasks | Task.is_recurring(), Task.next_occurrence(), Scheduler.complete_task() | Daily and weekly tasks automatically create a new copy of themselves after they're completed, so they stay on the schedule for the next day or week. One-time tasks don't repeat automatically.|

## 📸 Demo Walkthrough

PawPal+ is a Streamlit app (`app.py`) backed by the classes in `pawpal_system.py`.
Follow these steps to see it work:

1. **Enter the owner** — fill in name, birthday, email, and phone (e.g. "Jordan").
2. **Add a pet** — enter name, birthday, species, feeding frequency, and optional
   medication (e.g. "Mochi", a dog fed twice a day). A `💊 needs medication` note
   appears if you add one.
3. **Add tasks** — for each task set a title, duration, priority, frequency, and due
   date/time, then click **Add task** (e.g. "Morning walk", 20 min, high, daily, 08:00).
4. **Filter and manage tasks** — use the **all / pending / completed** toggle to
   narrow the list, check a task **done** (daily/weekly tasks 🔁 auto-queue the next
   occurrence), or **🗑** remove one.
5. **Build the schedule** — choose to order by **priority**, **date**, or **time**,
   then click **Generate schedule** for a plan with metric tiles, a sorted table, a
   "do this first" pick, and a ⚠️ conflict warning when two tasks share a time.

Key Scheduler behaviors on display: the three sort orders, the `next_task()`
recommendation, same-time `conflict_warning()`, and recurring-task roll-forward.

### Sample CLI output (`python main.py`)

The headless demo adds six daily tasks in scrambled time order (with both pets'
medication clashing at 12:00), then prints the schedule two ways plus the warning:

```text
══════════════════════════════════════════════════
  🔺  Today by PRIORITY
══════════════════════════════════════════════════
  07:30   ☐  Feed Buddy               HIGH    ( 5 min)
  12:00   ☐  Give Buddy medication    HIGH    ( 2 min)
  12:00   ☐  Give Mochi medication    HIGH    ( 2 min)
  08:00   ☐  Feed Mochi (breakfast)   MEDIUM  ( 5 min)
  17:00   ☐  Walk Buddy               MEDIUM  (30 min)
  18:30   ☐  Feed Mochi (dinner)      MEDIUM  ( 5 min)
──────────────────────────────────────────────────
  6 tasks · 49 min total · up next: Feed Buddy

══════════════════════════════════════════════════
  🕒  Today by TIME
══════════════════════════════════════════════════
  07:30   ☐  Feed Buddy               HIGH    ( 5 min)
  08:00   ☐  Feed Mochi (breakfast)   MEDIUM  ( 5 min)
  12:00   ☐  Give Buddy medication    HIGH    ( 2 min)
  12:00   ☐  Give Mochi medication    HIGH    ( 2 min)
  17:00   ☐  Walk Buddy               MEDIUM  (30 min)
  18:30   ☐  Feed Mochi (dinner)      MEDIUM  ( 5 min)
──────────────────────────────────────────────────
  6 tasks · 49 min total · up next: Feed Buddy

⚠️  Schedule conflict detected:
  • 2 tasks at 12:00: Give Buddy medication, Give Mochi medication
```

**Screenshot or video** *(optional)*: <!-- Insert a screenshot or link to a demo video here -->
