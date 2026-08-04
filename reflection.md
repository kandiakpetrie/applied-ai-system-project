# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
1) The program is supposed to create a daily plan/schedule for pet owners to keep up with their responsibilities pertaining to their pet. The program should take in the owners' schedule and basic info, the pets basic info and needs, and how long each task will take. 
- What classes did you include, and what responsibilities did you assign to each?
1)  The classes I would include are: Owner, Pet, Task, Scheduler. The Owner class would hold the personal info of the owner, so their name, birthday, number, and email. The Pet class would hold the info on the pets, so their name, birthday, kind of animal it is, what medication it's on (if it's on any), and how often it needs to eat. The Task class would hold each task as it's own objects. The Scheduler would hold the owner's schedule and how often the pet gets groomed (if it gets groomed), and how often their pet has to be taken outside.
2) The methods I would put in each class:
Owner: initializers that take in name, birthday, email and number, get and set methods for name, birthday, email and number. 
Pet: initializer for name, birthday, animal type, and feeding frequency,  get and set methods for name, birthday, animal type, and feeding frequency
Task: initalizers that create new tasks and set their priority level, get and set method to create tasks and their priority level, methods that add and remove tasks to a list, with each day being a new list, also a methods that add and remove tasks from a list for monthly tasks 
Scheduler: initializer to create a new schedule, a method that would organize the schedule based on date, a method that organizes the schedule based on priority level 

**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
1) The scheduler takes into account when task are scheduled, so tasks scheduled at the same time are flagged and priority is ranked if that's important to the user. 
- How did you decide which constraints mattered most?
1) I decided that priority came first and then time came after because if something needed to happen as soon as possible, then that was more important then the time other low priority tasks happened. 

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

1) ## Features / Implemented Algorithms

- **Task aggregation across pets** — `Owner.all_tasks()` flattens every pet's
  task list into one collection, and `Scheduler.build_schedule(owner)` pulls
  that into the working schedule so all pets are planned together.

- **Filtered task lookup** — `Owner.filter_tasks(pet_name, completed)` narrows
  tasks by pet and/or completion status. Both filters are optional and combine
  with AND; pet-name matching is case-insensitive, and `completed=False` is
  treated as a real filter (checked with `is None`) rather than "no filter".

- **Recurring-task generation** — `Task.next_occurrence()` rolls a task forward
  by frequency: DAILY advances the due date +1 day, WEEKLY +7 days; ONCE and
  MONTHLY produce no follow-up. It returns a fresh, not-completed copy
  (via `dataclasses.replace`) rather than mutating the original.

- **Auto-requeue on completion** — `Scheduler.complete_task()` marks a task done
  (keeping it as history) and, if it recurs, adds its next occurrence to the
  schedule so the chore reappears automatically.

- **Sort by date** — `organize_by_date()` orders tasks by due date then time,
  pushing undated tasks to the end.

- **Sort by time of day** — `sort_by_time()` orders by due time, with untimed
  tasks sorted last so `None` never breaks the comparison.

- **Sort by priority (with time tie-break)** — `organize_by_priority()` ranks
  most-urgent first (HIGH → MEDIUM → LOW); within a priority group, earlier
  times come first and untimed tasks sort last (using `inf` as the time key).

- **Next-task selection** — `next_task()` returns the single most urgent pending
  task, or `None` when everything is done.

- **Workload total** — `total_time()` sums the duration of all pending tasks.

- **Conflict detection** — `find_conflicts()` groups pending tasks by their
  exact (due_date, due_time) moment and returns any moment holding 2+ tasks;
  unscheduled and completed tasks are excluded. `has_conflicts()` gives a
  boolean, and `conflict_warning()` returns a human-readable message (empty
  string when clear) and never raises, so display can't crash the app.



---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
I used AI to help format my designs that were written in my original UML and fully florish it with my critiques and tweaks to the original plan. It also helped me debug issues in my algorithmic methods to make sure they were being executed how they were intended to execute.
- What kinds of prompts or questions were most helpful?
Based on this line (states line) or section, why is this output being produced instead of intended result...
Prompts and question that focus on a piece of a section instead of just an entire file. 

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
1) One time I didn't accept an AI suggestion as-is was when it generated the task sorting logic for the scheduler. I changed it so tasks without a due date or time would be placed at the end instead of causing sorting errors, since that worked better with how my app was designed.
- How did you evaluate or verify what the AI suggested?
1) I tested the code in the pytests by having the program creating tasks with different priorities, dates, and times. I also tried edge cases, like tasks without due dates, to make sure the scheduler behaved correctly and the app didn't crash.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
1) 
- Why were these tests important?
1) 

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
