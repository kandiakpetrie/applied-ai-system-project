"""PawPal+ data models and scheduling logic (skeleton).

Generated from diagrams/uml_draft.mmd. Method bodies are left as stubs for
you to implement.

Note on getters/setters: the UML lists explicit get/set methods for each
attribute. In Python, dataclass fields are already public attributes, so you
normally read/write them directly (e.g. `pet.name = "Mochi"`) instead of
writing boilerplate accessors. The stubs below follow that Pythonic style.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, time, timedelta
from enum import IntEnum
from typing import List, Optional


class Priority(IntEnum):
    """How urgent a task is (higher value = more urgent)."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class Frequency(IntEnum):
    """How often a task repeats."""

    ONCE = 0
    DAILY = 1
    WEEKLY = 2
    MONTHLY = 3


@dataclass
class Owner:
    """Holds the owner's personal info and manages their pets."""

    name: str
    birthday: date
    email: str
    number: str

    # Owns one or more pets and has a scheduler.
    pets: List["Pet"] = field(default_factory=list)
    scheduler: Optional["Scheduler"] = None

    def add_pet(self, pet: "Pet") -> None:
        """Add a pet to this owner."""
        self.pets.append(pet)

    def remove_pet(self, pet: "Pet") -> None:
        """Remove a pet from this owner (no error if it isn't there)."""
        if pet in self.pets:
            self.pets.remove(pet)

    def all_tasks(self) -> List["Task"]:
        """Return every task across all of this owner's pets."""
        return [task for pet in self.pets for task in pet.tasks]

    def pending_tasks(self) -> List["Task"]:
        """Return every not-yet-completed task across all pets."""
        return self.filter_tasks(completed=False)

    def filter_tasks(
        self,
        pet_name: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> List["Task"]:
        """Return tasks narrowed by pet name and/or completion status.

        Both filters are optional and combine (AND) when both are given:

        - ``filter_tasks()``                     -> every task (no filtering)
        - ``filter_tasks(pet_name="Mochi")``     -> only Mochi's tasks
        - ``filter_tasks(completed=False)``      -> only pending tasks
        - ``filter_tasks("Mochi", completed=True)`` -> Mochi's finished tasks

        Pet-name matching is case-insensitive. ``completed`` uses ``is None``
        (not a plain ``if completed``) so that ``completed=False`` still counts
        as an active filter rather than being treated as "no filter".
        """
        results: List["Task"] = []
        for pet in self.pets:
            if pet_name is not None and pet.name.lower() != pet_name.lower():
                continue
            for task in pet.tasks:
                if completed is not None and task.completed != completed:
                    continue
                results.append(task)
        return results

    def __str__(self) -> str:
        """Return a one-line summary of the owner and their task load."""
        return (
            f"{self.name} — {len(self.pets)} pet(s), "
            f"{len(self.all_tasks())} task(s), "
            f"{len(self.pending_tasks())} pending"
        )


@dataclass
class Pet:
    """Holds a pet's basic info, care needs, and the tasks it requires."""

    name: str
    birthday: date
    animal_type: str
    feeding_frequency: int  # times per day
    medication: Optional[str] = None

    # Tasks this pet requires (feeding, meds, grooming, etc.).
    tasks: List["Task"] = field(default_factory=list)

    def add_task(self, task: "Task") -> None:
        """Attach a care task to this pet."""
        self.tasks.append(task)

    def remove_task(self, task: "Task") -> None:
        """Detach a care task from this pet (no error if it isn't there)."""
        if task in self.tasks:
            self.tasks.remove(task)

    def pending_tasks(self) -> List["Task"]:
        """Return the tasks that still need to be done."""
        return [task for task in self.tasks if not task.completed]

    def needs_medication(self) -> bool:
        """Return True if this pet has a medication on record."""
        return self.medication is not None

    def __str__(self) -> str:
        """Return a one-line summary of the pet, its care needs, and tasks."""
        meds = self.medication if self.medication else "none"
        return (
            f"{self.name} ({self.animal_type}) — "
            f"fed {self.feeding_frequency}x/day, meds: {meds}, "
            f"{len(self.tasks)} task(s), {len(self.pending_tasks())} pending"
        )


@dataclass
class Task:
    """A single pet care activity (feeding, meds, a walk, grooming, etc.).

    A task describes *what* to do, *how long* it takes, *how often* it repeats,
    *how urgent* it is, and *whether it has been done*.
    """

    description: str
    duration: int = 0  # minutes the task takes
    frequency: Frequency = Frequency.ONCE
    priority_level: Priority = Priority.MEDIUM
    completed: bool = False

    # When the task is due: which day and what time of day it must be done.
    # (used by the Scheduler to order things).
    due_date: Optional[date] = None
    due_time: Optional[time] = None

    def mark_complete(self) -> None:
        """Mark this task as done."""
        self.completed = True

    def mark_incomplete(self) -> None:
        """Reset this task to not-yet-done (e.g. when it recurs)."""
        self.completed = False

    def is_recurring(self) -> bool:
        """Return True if the task repeats rather than happening only once."""
        return self.frequency != Frequency.ONCE

    def next_occurrence(self) -> Optional["Task"]:
        """Return a fresh, not-completed copy of this task for its next repeat.

        Only DAILY and WEEKLY tasks roll forward: DAILY advances the due date
        by one day, WEEKLY by seven. Returns ``None`` for ONCE (and MONTHLY),
        i.e. tasks that shouldn't spawn a daily/weekly follow-up.

        The copy keeps the same description, duration, frequency, priority and
        due *time*; only the ``due_date`` moves and ``completed`` resets to
        False. If the task has no ``due_date``, the copy stays undated (there is
        no date to advance) but is still reset to not-done.
        """
        steps = {
            Frequency.DAILY: timedelta(days=1),
            Frequency.WEEKLY: timedelta(weeks=1),
        }
        step = steps.get(self.frequency)
        if step is None:
            return None  # ONCE / MONTHLY don't produce a daily-or-weekly repeat

        next_date = self.due_date + step if self.due_date is not None else None
        # dataclasses.replace() builds a NEW Task, copying every field except the
        # ones we override here -> a genuinely separate instance, not an alias.
        return replace(self, completed=False, due_date=next_date)

    def __str__(self) -> str:
        """Return a one-line summary of the task and its status."""
        status = "✓" if self.completed else "✗"
        when = f", due {self.due_time.strftime('%H:%M')}" if self.due_time else ""
        return (
            f"[{status}] {self.description} "
            f"({self.duration} min, {self.frequency.name.lower()}, "
            f"priority {self.priority_level.name.lower()}{when})"
        )


class Scheduler:
    """The "brain" that retrieves, organizes, and manages tasks across pets."""

    def __init__(self, grooming_frequency: int = 0, walk_frequency: int = 0) -> None:
        """Create an empty scheduler with grooming/walk frequency settings."""
        self.schedule: List[Task] = []
        self.grooming_frequency = grooming_frequency  # times per month
        self.walk_frequency = walk_frequency  # times per day

    # --- retrieve ---------------------------------------------------------

    def build_schedule(self, owner: "Owner") -> List[Task]:
        """Pull every task from all of the owner's pets into the schedule."""
        self.schedule = owner.all_tasks()
        return self.schedule

    def add_task(self, task: Task) -> None:
        """Add a single task to the schedule."""
        self.schedule.append(task)

    def remove_task(self, task: Task) -> None:
        """Remove a task from the schedule (no error if it isn't there)."""
        if task in self.schedule:
            self.schedule.remove(task)

    # --- organize ---------------------------------------------------------

    def organize_by_date(self) -> List[Task]:
        """Return the schedule ordered by due date then time (undated last)."""
        return sorted(
            self.schedule,
            key=lambda task: (
                task.due_date is None,
                task.due_date or date.max,
                task.due_time or time.max,
            ),
        )

    def sort_by_time(self) -> List[Task]:
        """Return the schedule ordered by due time of day (untimed tasks last).

        Sorts purely on ``due_time`` (e.g. the 07:00 feeding comes before the
        18:00 walk). Tasks with no ``due_time`` set are pushed to the end
        instead of crashing, because ``None`` can't be compared to a ``time``.
        """
        return sorted(
            self.schedule,
            key=lambda task: (
                task.due_time is None,          # False (0) sorts before True (1)
                task.due_time or time.max,      # placeholder so the key never sees None
            ),
        )

    def organize_by_priority(self) -> List[Task]:
        """Return the schedule ordered by priority, then by time ascending.

        Primary sort: priority, most urgent first (HIGH -> MEDIUM -> LOW).
        Tie-break: within the same priority, earlier times come first
        (e.g. a 07:00 task before an 18:00 one). Tasks with no ``due_time``
        sort to the end of their priority group.

        The key uses ``-task.priority_level`` so a single ascending ``sorted``
        still puts HIGH (3) first, while time stays in natural ascending order;
        untimed tasks get ``inf`` so they land last within their group.
        """

        def time_key(task: Task) -> float:
            """Return a task's due time as minutes since midnight for sorting.

            Untimed tasks return ``inf`` so they sort last within their priority
            group; timed tasks return ``hour * 60 + minute`` (smaller = earlier).
            """
            if task.due_time is None:
                return float("inf")  # untimed tasks last within their priority
            return task.due_time.hour * 60 + task.due_time.minute

        return sorted(
            self.schedule,
            key=lambda task: (-int(task.priority_level), time_key(task)),
        )

    # --- manage -----------------------------------------------------------

    def complete_task(self, task: Task) -> Optional[Task]:
        """Mark a task done and queue its next occurrence if it recurs.

        Marks ``task`` complete (it stays in the schedule as history). If it is
        a DAILY or WEEKLY task, a fresh not-completed copy is created for the
        next date via ``Task.next_occurrence()`` and added to the schedule, so
        the recurring chore reappears automatically. Returns the newly created
        task, or ``None`` when nothing was queued (one-time/monthly tasks).
        """
        task.mark_complete()
        follow_up = task.next_occurrence()
        if follow_up is not None:
            self.add_task(follow_up)
        return follow_up

    def pending_tasks(self) -> List[Task]:
        """Return the tasks in the schedule that still need to be done."""
        return [task for task in self.schedule if not task.completed]

    def next_task(self) -> Optional[Task]:
        """Return the most urgent pending task, or None if all are done."""
        pending = self.pending_tasks()
        if not pending:
            return None
        return max(pending, key=lambda task: task.priority_level)

    def total_time(self) -> int:
        """Return the total minutes needed for all pending tasks."""
        return sum(task.duration for task in self.pending_tasks())

    # --- conflicts --------------------------------------------------------

    def find_conflicts(self) -> List[List[Task]]:
        """Return groups of pending tasks that fall on the same date and time.

        Two tasks "clash" when they share the exact same ``due_date`` AND
        ``due_time`` — the owner can't be doing both at once, even if they are
        for different pets. Tasks are grouped by that (date, time) moment, and
        only moments with 2+ tasks are returned (each inner list is one clash).

        Tasks with no ``due_date`` or no ``due_time`` can't be pinned to a
        moment, so they're skipped. Completed tasks are ignored too — a chore
        already done doesn't compete for time.
        """
        by_moment: dict = {}
        for task in self.pending_tasks():
            if task.due_date is None or task.due_time is None:
                continue  # unscheduled tasks can't collide with anything
            moment = (task.due_date, task.due_time)
            by_moment.setdefault(moment, []).append(task)

        # Keep only the moments where more than one task landed.
        return [tasks for tasks in by_moment.values() if len(tasks) > 1]

    def has_conflicts(self) -> bool:
        """Return True if any two pending tasks are scheduled at the same time."""
        return bool(self.find_conflicts())

    def conflict_warning(self) -> str:
        """Return a human-readable warning about time clashes (never raises).

        This is the "lightweight" check: instead of throwing an exception when
        two tasks collide, it returns a friendly message the caller can print
        as-is. When there are no conflicts it returns an empty string ``""``,
        which is falsy — so callers can simply do::

            warning = scheduler.conflict_warning()
            if warning:
                print(warning)

        The whole body is defensive: any unexpected error is swallowed and
        reported as a generic notice, so a display glitch can never crash the
        program that's just trying to show a schedule.
        """
        try:
            conflicts = self.find_conflicts()
            if not conflicts:
                return ""  # empty string is falsy -> "no warning"

            lines = ["⚠️  Schedule conflict detected:"]
            for group in conflicts:
                # Every task in a group shares the same moment, so read it off
                # the first one.
                moment = group[0]
                when = moment.due_time.strftime("%H:%M")
                names = ", ".join(task.description for task in group)
                lines.append(f"  • {len(group)} tasks at {when}: {names}")
            return "\n".join(lines)
        except Exception:
            # Last-resort guard: detection should never take the app down.
            return "⚠️  Could not check for schedule conflicts."
