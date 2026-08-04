"""PawPal+ demo: build an owner with pets and print today's schedule."""

from datetime import date, time

from pawpal_system import Owner, Pet, Task, Scheduler, Priority, Frequency

if __name__ == "__main__":
    # 1. Create a pet owner.
    owner = Owner(
        name="Alice",
        birthday=date(1995, 3, 12),
        email="alice@example.com",
        number="555-0100",
    )

    # 2. Create at least two pets and add them to the owner.
    buddy = Pet(
        name="Buddy",
        birthday=date(2020, 5, 15),
        animal_type="Dog",
        feeding_frequency=2,
        medication="Heartworm prevention",
    )
    mochi = Pet(
        name="Mochi",
        birthday=date(2021, 8, 1),
        animal_type="Cat",
        feeding_frequency=3,
    )
    owner.add_pet(buddy)
    owner.add_pet(mochi)

    # 3. Add tasks in a deliberately scrambled time order. They are NOT added
    #    chronologically, so if the printed schedule comes out in time order it
    #    proves the Scheduler is doing the sorting (not just echoing input).
    today = date(2026, 7, 5)
    buddy.add_task(Task(
        description="Walk Buddy",
        duration=30,
        frequency=Frequency.DAILY,
        priority_level=Priority.MEDIUM,
        due_date=today,
        due_time=time(17, 0),        # evening
    ))
    mochi.add_task(Task(
        description="Give Mochi medication",
        duration=2,
        frequency=Frequency.DAILY,
        priority_level=Priority.HIGH,
        due_date=today,
        due_time=time(12, 0),        # midday
    ))
    buddy.add_task(Task(
        description="Feed Buddy",
        duration=5,
        frequency=Frequency.DAILY,
        priority_level=Priority.HIGH,
        due_date=today,
        due_time=time(7, 30),        # early morning
    ))
    mochi.add_task(Task(
        description="Feed Mochi (dinner)",
        duration=5,
        frequency=Frequency.DAILY,
        priority_level=Priority.MEDIUM,
        due_date=today,
        due_time=time(18, 30),       # evening
    ))
    mochi.add_task(Task(
        description="Feed Mochi (breakfast)",
        duration=5,
        frequency=Frequency.DAILY,
        priority_level=Priority.MEDIUM,
        due_date=today,
        due_time=time(8, 0),         # morning
    ))
    # A deliberate clash: Buddy's meds land at 12:00 — the SAME time as Mochi's
    # medication above. Different pets, same moment -> the owner can't do both.
    buddy.add_task(Task(
        description="Give Buddy medication",
        duration=2,
        frequency=Frequency.DAILY,
        priority_level=Priority.HIGH,
        due_date=today,
        due_time=time(12, 0),        # ⚠️ collides with "Give Mochi medication"
    ))

    # 4. Build the schedule once, then print it two different ways.
    scheduler = Scheduler()
    scheduler.build_schedule(owner)

    def print_schedule(header: str, tasks: list) -> None:
        """Print a titled, aligned table for an already-ordered task list."""
        # Size the description column to the longest task so columns line up.
        desc_width = max((len(t.description) for t in tasks), default=0)

        print("═" * 50)
        print(f"  {header}")
        print("═" * 50)

        for task in tasks:
            when = task.due_time.strftime("%H:%M") if task.due_time else "  —  "
            box = "☑" if task.completed else "☐"
            print(
                f"  {when}   {box}  {task.description.ljust(desc_width)}   "
                f"{task.priority_level.name:<7} ({task.duration:>2} min)"
            )

        print("─" * 50)
        summary = f"{len(tasks)} tasks · {scheduler.total_time()} min total"
        next_up = scheduler.next_task()
        if next_up:
            summary += f" · up next: {next_up.description}"
        print(f"  {summary}")

    # First view: ordered by priority (most urgent first).
    print_schedule("🔺  Today by PRIORITY", scheduler.organize_by_priority())

    print()  # blank line between the two tables

    # Second view: ordered by time of day (earliest first).
    print_schedule("🕒  Today by TIME", scheduler.sort_by_time())

    # Warn about any tasks competing for the same moment. conflict_warning()
    # returns "" (falsy) when the day is clear, so this prints nothing then.
    warning = scheduler.conflict_warning()
    if warning:
        print()
        print(warning)
