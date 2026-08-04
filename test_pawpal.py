"""Lightweight tests for PawPal+ sorting and filtering logic.

Run with:  python3 test_pawpal.py

No test framework needed — each check prints PASS/FAIL and the script ends
with a summary line and a non-zero exit code if anything failed.
"""

from datetime import date, time

from pawpal_system import Owner, Pet, Task, Scheduler, Priority, Frequency

# --- tiny test harness ----------------------------------------------------

_passed = 0
_failed = 0


def check(name: str, got, expected) -> None:
    """Compare got vs expected, print a PASS/FAIL line, and tally results."""
    global _passed, _failed
    if got == expected:
        _passed += 1
        print(f"  ✅ PASS  {name}")
    else:
        _failed += 1
        print(f"  ❌ FAIL  {name}")
        print(f"           expected: {expected}")
        print(f"           got:      {got}")


def descs(tasks) -> list:
    """Reduce a list of Task objects to their descriptions for easy comparison."""
    return [t.description for t in tasks]


# --- shared test fixture --------------------------------------------------

def make_owner() -> Owner:
    """Build an owner with two pets and tasks added in a scrambled order.

    Times/dates/priorities/completion are all known, so every method's
    correct output is predictable.
    """
    owner = Owner(name="Alice", birthday=date(1995, 3, 12),
                  email="a@x.com", number="555")
    buddy = Pet(name="Buddy", birthday=date(2020, 5, 15),
                animal_type="Dog", feeding_frequency=2)
    mochi = Pet(name="Mochi", birthday=date(2021, 8, 1),
                animal_type="Cat", feeding_frequency=3)
    owner.add_pet(buddy)
    owner.add_pet(mochi)

    d1 = date(2026, 7, 5)
    d2 = date(2026, 7, 6)

    # Added out of order on purpose (see descriptions vs times).
    buddy.add_task(Task("Walk Buddy", 30, Frequency.DAILY, Priority.MEDIUM,
                        completed=False, due_date=d1, due_time=time(17, 0)))
    mochi.add_task(Task("Med Mochi", 2, Frequency.DAILY, Priority.HIGH,
                        completed=True, due_date=d1, due_time=time(12, 0)))
    buddy.add_task(Task("Feed Buddy", 5, Frequency.DAILY, Priority.HIGH,
                        completed=False, due_date=d1, due_time=time(7, 30)))
    # A task on the NEXT day and one with NO due time, to test tie/None handling.
    mochi.add_task(Task("Vet Mochi", 45, Frequency.ONCE, Priority.LOW,
                        completed=False, due_date=d2, due_time=time(9, 0)))
    buddy.add_task(Task("Groom Buddy", 20, Frequency.MONTHLY, Priority.LOW,
                        completed=False, due_date=None, due_time=None))
    return owner


# --- tests ----------------------------------------------------------------

def test_sorting() -> None:
    print("\nSORTING METHODS")
    owner = make_owner()
    sched = Scheduler()
    sched.build_schedule(owner)

    # organize_by_date: chronological (date, then time); undated task last.
    check(
        "organize_by_date orders by date+time, undated last",
        descs(sched.organize_by_date()),
        ["Feed Buddy", "Med Mochi", "Walk Buddy", "Vet Mochi", "Groom Buddy"],
    )

    # sort_by_time: time-of-day only, ignoring the date. So next-day 09:00
    # (Vet Mochi) sorts among today's times; untimed task last.
    check(
        "sort_by_time orders by time of day, untimed last",
        descs(sched.sort_by_time()),
        ["Feed Buddy", "Vet Mochi", "Med Mochi", "Walk Buddy", "Groom Buddy"],
    )

    # organize_by_priority: HIGH first, LOW last; within a priority, earlier
    # times come first (time ascending), untimed tasks last in their group.
    #   HIGH: Feed Buddy (07:30) before Med Mochi (12:00)
    #   MED:  Walk Buddy (17:00)
    #   LOW:  Vet Mochi (09:00) before Groom Buddy (no time -> last)
    check(
        "organize_by_priority: priority first, then time ascending",
        descs(sched.organize_by_priority()),
        ["Feed Buddy", "Med Mochi", "Walk Buddy", "Vet Mochi", "Groom Buddy"],
    )

    # next_task: most urgent PENDING task. Med Mochi is HIGH but completed,
    # so it should be skipped -> Feed Buddy (the other HIGH) wins.
    nt = sched.next_task()
    check("next_task skips completed and returns most urgent pending",
          nt.description if nt else None, "Feed Buddy")


def test_filtering() -> None:
    print("\nFILTERING METHODS")
    owner = make_owner()

    check("filter_tasks() with no args returns every task",
          len(owner.filter_tasks()), 5)

    check("filter_tasks(pet_name='Buddy') returns only Buddy's tasks",
          sorted(descs(owner.filter_tasks(pet_name="Buddy"))),
          ["Feed Buddy", "Groom Buddy", "Walk Buddy"])

    check("filter_tasks pet_name is case-insensitive",
          len(owner.filter_tasks(pet_name="mOcHi")), 2)

    check("filter_tasks(completed=True) returns only finished tasks",
          descs(owner.filter_tasks(completed=True)), ["Med Mochi"])

    check("filter_tasks(completed=False) returns only pending tasks",
          len(owner.filter_tasks(completed=False)), 4)

    check("filter_tasks combines pet_name AND completed",
          descs(owner.filter_tasks(pet_name="Mochi", completed=True)),
          ["Med Mochi"])

    check("filter_tasks unknown pet returns empty list",
          owner.filter_tasks(pet_name="Nobody"), [])

    # pending_tasks now delegates to filter_tasks(completed=False):
    # both must agree.
    check("pending_tasks matches filter_tasks(completed=False)",
          descs(owner.pending_tasks()),
          descs(owner.filter_tasks(completed=False)))


if __name__ == "__main__":
    print("=" * 52)
    print("  PawPal+ sorting & filtering tests")
    print("=" * 52)

    test_sorting()
    test_filtering()

    print("\n" + "-" * 52)
    total = _passed + _failed
    print(f"  Results: {_passed}/{total} passed, {_failed} failed")
    print("-" * 52)

    raise SystemExit(1 if _failed else 0)
