"""Tests for PawPal+ core behavior."""

import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task


def make_pet(name="Mochi", **kwargs):
    """Helper to build a Pet with sensible defaults."""
    defaults = dict(
        birthday=date(2020, 1, 1),
        animal_type="cat",
        feeding_frequency=2,
    )
    defaults.update(kwargs)
    return Pet(name=name, **defaults)


# --- Task -----------------------------------------------------------------

def test_task_completion():
    """mark_complete() should change a task's status to completed."""
    task = Task(description="Feed Mochi")

    # A new task starts out not completed.
    assert task.completed is False

    task.mark_complete()

    assert task.completed is True


def test_task_mark_incomplete():
    """mark_incomplete() should reset a completed task to not-done."""
    task = Task(description="Walk dog", completed=True)

    task.mark_incomplete()

    assert task.completed is False


def test_task_is_recurring():
    """is_recurring() is True for repeating tasks, False for one-time ones."""
    once = Task(description="Vet visit", frequency=Frequency.ONCE)
    daily = Task(description="Feeding", frequency=Frequency.DAILY)

    assert once.is_recurring() is False
    assert daily.is_recurring() is True


def test_next_occurrence_daily_advances_one_day():
    """A DAILY task's next occurrence is one day later, reset to not-done."""
    task = Task(
        description="Feed Mochi",
        frequency=Frequency.DAILY,
        completed=True,
        due_date=date(2026, 7, 5),
        due_time=time(8, 0),
    )

    nxt = task.next_occurrence()

    assert nxt is not None
    assert nxt.due_date == date(2026, 7, 6)   # +1 day
    assert nxt.due_time == time(8, 0)          # same time of day
    assert nxt.completed is False              # fresh copy is not done
    assert nxt is not task                      # a genuinely new instance


def test_next_occurrence_weekly_advances_seven_days():
    """A WEEKLY task's next occurrence is seven days later."""
    task = Task(
        description="Bath",
        frequency=Frequency.WEEKLY,
        completed=True,
        due_date=date(2026, 7, 5),
    )

    nxt = task.next_occurrence()

    assert nxt is not None
    assert nxt.due_date == date(2026, 7, 12)  # +7 days
    assert nxt.completed is False


def test_next_occurrence_once_returns_none():
    """One-time (and monthly) tasks don't produce a daily/weekly follow-up."""
    once = Task(description="Vet visit", frequency=Frequency.ONCE)
    monthly = Task(description="Flea med", frequency=Frequency.MONTHLY)

    assert once.next_occurrence() is None
    assert monthly.next_occurrence() is None


def test_next_occurrence_without_date_stays_undated():
    """A recurring task with no due date resets to not-done but stays undated."""
    task = Task(description="Feed", frequency=Frequency.DAILY, completed=True)

    nxt = task.next_occurrence()

    assert nxt is not None
    assert nxt.due_date is None
    assert nxt.completed is False


# --- Pet ------------------------------------------------------------------

def test_task_addition():
    """Adding a task to a Pet should increase that pet's task count."""
    pet = make_pet()

    # A new pet starts with no tasks.
    assert len(pet.tasks) == 0

    pet.add_task(Task(description="Feed Mochi"))

    assert len(pet.tasks) == 1


def test_task_removal():
    """Removing a task from a Pet should decrease its task count."""
    pet = make_pet()
    task = Task(description="Feed Mochi")
    pet.add_task(task)

    pet.remove_task(task)

    assert len(pet.tasks) == 0


def test_pet_pending_tasks():
    """pending_tasks() should exclude tasks already marked complete."""
    pet = make_pet()
    done = Task(description="Morning feed", completed=True)
    todo = Task(description="Evening feed")
    pet.add_task(done)
    pet.add_task(todo)

    pending = pet.pending_tasks()

    assert pending == [todo]


def test_pet_needs_medication():
    """needs_medication() reflects whether a medication is on record."""
    healthy = make_pet()
    treated = make_pet(medication="insulin")

    assert healthy.needs_medication() is False
    assert treated.needs_medication() is True


# --- Owner ----------------------------------------------------------------

def test_owner_all_and_pending_tasks():
    """Owner aggregates tasks across all pets and tracks pending ones."""
    owner = Owner(
        name="Kandi",
        birthday=date(1995, 5, 5),
        email="k@example.com",
        number="555-0100",
    )
    pet = make_pet()
    pet.add_task(Task(description="Feed", completed=True))
    pet.add_task(Task(description="Walk"))
    owner.add_pet(pet)

    assert len(owner.all_tasks()) == 2
    assert len(owner.pending_tasks()) == 1


# --- Scheduler ------------------------------------------------------------

def test_scheduler_next_task_picks_highest_priority():
    """next_task() returns the most urgent pending task."""
    scheduler = Scheduler()
    low = Task(description="Groom", priority_level=Priority.LOW)
    high = Task(description="Give meds", priority_level=Priority.HIGH)
    scheduler.add_task(low)
    scheduler.add_task(high)

    assert scheduler.next_task() is high


def test_scheduler_total_time_counts_only_pending():
    """total_time() sums durations of pending tasks only."""
    scheduler = Scheduler()
    scheduler.add_task(Task(description="Walk", duration=30))
    scheduler.add_task(Task(description="Feed", duration=10, completed=True))

    assert scheduler.total_time() == 30


def test_scheduler_organize_by_date():
    """organize_by_date() orders dated tasks first, undated last."""
    scheduler = Scheduler()
    later = Task(description="Later", due_date=date(2026, 7, 10), due_time=time(9, 0))
    sooner = Task(description="Sooner", due_date=date(2026, 7, 6), due_time=time(8, 0))
    undated = Task(description="Whenever")
    scheduler.add_task(later)
    scheduler.add_task(undated)
    scheduler.add_task(sooner)

    assert scheduler.organize_by_date() == [sooner, later, undated]


def test_scheduler_complete_task_queues_next_occurrence():
    """Completing a DAILY task marks it done and adds tomorrow's copy."""
    scheduler = Scheduler()
    feeding = Task(
        description="Feed Mochi",
        frequency=Frequency.DAILY,
        due_date=date(2026, 7, 5),
        due_time=time(8, 0),
    )
    scheduler.add_task(feeding)

    follow_up = scheduler.complete_task(feeding)

    # Original is now done; a new pending copy exists for the next day.
    assert feeding.completed is True
    assert follow_up is not None
    assert follow_up.due_date == date(2026, 7, 6)
    assert follow_up.completed is False
    assert len(scheduler.schedule) == 2               # original + follow-up
    assert scheduler.pending_tasks() == [follow_up]   # only the new one is pending


def test_scheduler_complete_task_once_queues_nothing():
    """Completing a one-time task marks it done but queues no follow-up."""
    scheduler = Scheduler()
    vet = Task(description="Vet visit", frequency=Frequency.ONCE)
    scheduler.add_task(vet)

    follow_up = scheduler.complete_task(vet)

    assert vet.completed is True
    assert follow_up is None
    assert len(scheduler.schedule) == 1  # nothing added


def test_scheduler_detects_same_time_conflict():
    """Two tasks at the same date+time are reported as one conflict group."""
    scheduler = Scheduler()
    when = dict(due_date=date(2026, 7, 5), due_time=time(8, 0))
    feed = Task(description="Feed Buddy", **when)
    med = Task(description="Med Mochi", **when)   # different pet, same moment
    walk = Task(description="Walk", due_date=date(2026, 7, 5), due_time=time(17, 0))
    scheduler.add_task(feed)
    scheduler.add_task(med)
    scheduler.add_task(walk)

    conflicts = scheduler.find_conflicts()

    assert scheduler.has_conflicts() is True
    assert len(conflicts) == 1                    # one clashing moment
    assert len(conflicts[0]) == 2                 # exactly two tasks clash
    assert feed in conflicts[0] and med in conflicts[0]   # the two 08:00 tasks
    assert walk not in conflicts[0]               # 17:00 task is clear


def test_scheduler_no_conflict_when_times_differ():
    """Tasks at different times (or unscheduled) produce no conflicts."""
    scheduler = Scheduler()
    scheduler.add_task(Task(description="A", due_date=date(2026, 7, 5), due_time=time(8, 0)))
    scheduler.add_task(Task(description="B", due_date=date(2026, 7, 5), due_time=time(9, 0)))
    scheduler.add_task(Task(description="Whenever"))  # no date/time -> can't clash

    assert scheduler.find_conflicts() == []
    assert scheduler.has_conflicts() is False


def test_conflict_warning_returns_message_on_clash():
    """conflict_warning() returns a non-empty, informative string on a clash."""
    scheduler = Scheduler()
    when = dict(due_date=date(2026, 7, 5), due_time=time(8, 0))
    scheduler.add_task(Task(description="Feed Buddy", **when))
    scheduler.add_task(Task(description="Med Mochi", **when))

    warning = scheduler.conflict_warning()

    assert warning != ""              # truthy -> there is a warning
    assert "08:00" in warning         # names the clashing time
    assert "Feed Buddy" in warning
    assert "Med Mochi" in warning


def test_conflict_warning_empty_when_clear():
    """conflict_warning() returns '' (falsy) when there are no conflicts."""
    scheduler = Scheduler()
    scheduler.add_task(Task(description="A", due_date=date(2026, 7, 5), due_time=time(8, 0)))
    scheduler.add_task(Task(description="B", due_date=date(2026, 7, 5), due_time=time(9, 0)))

    assert scheduler.conflict_warning() == ""
    assert not scheduler.conflict_warning()  # falsy, so `if warning:` skips it


def test_scheduler_conflict_ignores_completed_and_other_dates():
    """A completed task, or a same-time task on another day, isn't a conflict."""
    scheduler = Scheduler()
    t1 = Task(description="Active", due_date=date(2026, 7, 5), due_time=time(8, 0))
    done = Task(description="Done", due_date=date(2026, 7, 5), due_time=time(8, 0),
                completed=True)                                   # same moment but finished
    other_day = Task(description="Tomorrow", due_date=date(2026, 7, 6), due_time=time(8, 0))
    scheduler.add_task(t1)
    scheduler.add_task(done)
    scheduler.add_task(other_day)

    assert scheduler.has_conflicts() is False


# --- next_occurrence: boundary + independence -----------------------------

def test_next_occurrence_daily_crosses_year_boundary():
    """A DAILY task due Dec 31 rolls forward to Jan 1 of the next year."""
    task = Task(
        description="Feed",
        frequency=Frequency.DAILY,
        completed=True,
        due_date=date(2026, 12, 31),
        due_time=time(8, 0),
    )

    nxt = task.next_occurrence()

    assert nxt.due_date == date(2027, 1, 1)   # month AND year advance


def test_next_occurrence_weekly_crosses_month_boundary():
    """A WEEKLY task near month end rolls into the following month."""
    task = Task(
        description="Bath",
        frequency=Frequency.WEEKLY,
        due_date=date(2026, 7, 28),
    )

    nxt = task.next_occurrence()

    assert nxt.due_date == date(2026, 8, 4)   # +7 days spills into August


def test_next_occurrence_copy_is_independent_of_original():
    """Mutating the rolled-forward copy must not touch the original task."""
    original = Task(
        description="Feed Mochi",
        frequency=Frequency.DAILY,
        completed=True,
        due_date=date(2026, 7, 5),
    )

    nxt = original.next_occurrence()
    nxt.description = "Changed"
    nxt.mark_complete()

    # The original is a genuinely separate object (dataclasses.replace),
    # so editing the copy leaves it untouched.
    assert original.description == "Feed Mochi"
    assert original.completed is True          # original stays done (history)
    assert original.due_date == date(2026, 7, 5)


def test_monthly_is_recurring_but_never_rolls_forward():
    """Documents a known quirk: MONTHLY reads as recurring yet never repeats.

    is_recurring() returns True for MONTHLY (so the UI shows the 🔁 badge),
    but next_occurrence() only advances DAILY/WEEKLY, so a completed monthly
    task silently produces no follow-up. Pinning this so the behavior is a
    deliberate choice rather than a latent surprise.
    """
    monthly = Task(description="Flea med", frequency=Frequency.MONTHLY,
                   due_date=date(2026, 7, 5))

    assert monthly.is_recurring() is True       # shown as recurring...
    assert monthly.next_occurrence() is None    # ...but never spawns a copy


# --- sort_by_time ---------------------------------------------------------

def test_sort_by_time_orders_by_time_of_day_ignoring_date():
    """sort_by_time() sorts on time-of-day only; the due date is irrelevant."""
    scheduler = Scheduler()
    # Deliberately give the EARLIEST time-of-day the LATEST date, so a
    # date-aware sort would order these differently than a time-only sort.
    morning = Task(description="Morning", due_date=date(2026, 7, 10), due_time=time(7, 0))
    noon = Task(description="Noon", due_date=date(2026, 7, 5), due_time=time(12, 0))
    evening = Task(description="Evening", due_date=date(2026, 7, 6), due_time=time(18, 0))
    scheduler.add_task(evening)
    scheduler.add_task(morning)
    scheduler.add_task(noon)

    assert scheduler.sort_by_time() == [morning, noon, evening]


def test_sort_by_time_pushes_untimed_tasks_last():
    """Tasks with no due_time sort after every timed task (no crash on None)."""
    scheduler = Scheduler()
    timed = Task(description="Timed", due_time=time(9, 0))
    untimed = Task(description="Untimed")   # due_time is None
    scheduler.add_task(untimed)
    scheduler.add_task(timed)

    assert scheduler.sort_by_time() == [timed, untimed]


def test_sort_by_time_treats_midnight_as_earliest_not_missing():
    """A midnight (00:00) task must sort first, not be mistaken for 'no time'.

    Guards the `task.due_time or time.max` idiom: time(0,0) is truthy in
    modern Python, so midnight stays an early time rather than collapsing to
    the time.max sentinel used for untimed tasks.
    """
    scheduler = Scheduler()
    midnight = Task(description="Midnight", due_time=time(0, 0))
    morning = Task(description="Morning", due_time=time(8, 0))
    untimed = Task(description="Untimed")
    scheduler.add_task(untimed)
    scheduler.add_task(morning)
    scheduler.add_task(midnight)

    assert scheduler.sort_by_time() == [midnight, morning, untimed]


# --- organize_by_priority -------------------------------------------------

def test_organize_by_priority_high_first_then_time_ascending():
    """Sorts by priority (HIGH->LOW); within a tier, earlier times come first."""
    scheduler = Scheduler()
    high_late = Task(description="HighLate", priority_level=Priority.HIGH, due_time=time(12, 0))
    high_early = Task(description="HighEarly", priority_level=Priority.HIGH, due_time=time(7, 30))
    med = Task(description="Med", priority_level=Priority.MEDIUM, due_time=time(17, 0))
    low_timed = Task(description="LowTimed", priority_level=Priority.LOW, due_time=time(9, 0))
    low_untimed = Task(description="LowUntimed", priority_level=Priority.LOW)
    for t in (med, low_untimed, high_late, low_timed, high_early):
        scheduler.add_task(t)

    assert scheduler.organize_by_priority() == [
        high_early,   # HIGH 07:30
        high_late,    # HIGH 12:00
        med,          # MEDIUM 17:00
        low_timed,    # LOW 09:00
        low_untimed,  # LOW, no time -> last in its group
    ]


def test_organize_by_priority_is_stable_on_full_ties():
    """Tasks with identical priority AND time keep their insertion order."""
    scheduler = Scheduler()
    first = Task(description="First", priority_level=Priority.HIGH, due_time=time(8, 0))
    second = Task(description="Second", priority_level=Priority.HIGH, due_time=time(8, 0))
    scheduler.add_task(first)
    scheduler.add_task(second)

    # sorted() is stable, so the tie resolves to the order they were added.
    assert scheduler.organize_by_priority() == [first, second]


# --- sorting: empty / all-None inputs -------------------------------------

def test_sorts_handle_empty_schedule():
    """Every sort returns an empty list on an empty schedule (no crash)."""
    scheduler = Scheduler()

    assert scheduler.organize_by_date() == []
    assert scheduler.sort_by_time() == []
    assert scheduler.organize_by_priority() == []


def test_sorts_handle_all_untimed_tasks():
    """With no dates/times set, sorts still succeed and keep every task."""
    scheduler = Scheduler()
    a = Task(description="A")
    b = Task(description="B")
    scheduler.add_task(a)
    scheduler.add_task(b)

    # None of the None-valued keys should raise; all tasks survive.
    assert len(scheduler.organize_by_date()) == 2
    assert len(scheduler.sort_by_time()) == 2
    assert len(scheduler.organize_by_priority()) == 2


# --- next_task / conflicts: remaining edges -------------------------------

def test_next_task_returns_none_when_all_completed():
    """next_task() is None once no pending task remains."""
    scheduler = Scheduler()
    scheduler.add_task(Task(description="Done1", completed=True))
    scheduler.add_task(Task(description="Done2", completed=True))

    assert scheduler.next_task() is None


def test_conflict_groups_three_tasks_at_one_moment():
    """Three tasks sharing a moment form a single group of three, not pairs."""
    scheduler = Scheduler()
    when = dict(due_date=date(2026, 7, 5), due_time=time(8, 0))
    a = Task(description="A", **when)
    b = Task(description="B", **when)
    c = Task(description="C", **when)
    for t in (a, b, c):
        scheduler.add_task(t)

    conflicts = scheduler.find_conflicts()

    assert len(conflicts) == 1        # one clashing moment
    assert len(conflicts[0]) == 3     # all three tasks, grouped together
