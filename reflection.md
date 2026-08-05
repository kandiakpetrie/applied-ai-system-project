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

1) Yes, it changed in a couple of places. My original UML had get and set methods
for every attribute, but once I started writing it in Python I dropped them, since
dataclass fields are already public and the getters were just extra code that
didn't do anything.

2) I also added due_date and due_time to the Task class, which weren't in my first
design. I needed them once I realized the scheduler couldn't sort tasks by time of
day or catch two tasks landing at the same moment without them.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
1) The scheduler takes into account when task are scheduled, so tasks scheduled at the same time are flagged and priority is ranked if that's important to the user. 
- How did you decide which constraints mattered most?
1) I decided that priority came first and then time came after because if something needed to happen as soon as possible, then that was more important then the time other low priority tasks happened. 

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.

1) One tradeoff my scheduler makes is that it only flags a conflict when two
tasks have the exact same date and time, and it only warns the user instead of
moving anything. So a 30 minute walk at 17:00 and another task at 17:15 won't get
flagged even though they overlap.

- Why is that tradeoff reasonable for this scenario?

2) It's reasonable because the owner knows their own day better than my app does.
A warning they can act on is more useful than the app rearranging their schedule
for them, and it also means a conflict never crashes the program, it just shows a
message.

---

## Features / Implemented Algorithms

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

1) **Scheduler behaviors (37 tests, `tests/test_pawpal.py`)** — the three sort
   orders (`organize_by_date`, `sort_by_time`, `organize_by_priority`), including
   priority ties broken by time and untimed tasks pushed to the end; filtering by
   pet and by completion status; `next_task()` selection; `total_time()`;
   same-moment conflict detection and grouping; and recurring-task roll-forward
   through `next_occurrence()` / `complete_task()`.

2) **RAG behaviors (48 tests, `tests/test_rag.py`)** — tokenizing and stemming;
   corpus loading and heading-based chunking; retrieval ranking, `top_k`, and the
   score floor; query expansion (both that it helps *and* that it cannot outvote
   the question); the three answering modes; that the snippets handed to the model
   are exactly the ones retrieved; that the live schedule reaches the prompt; and
   every guardrail (input validation, health escalation, refusal wording).

- Why were these tests important?

1) The scheduler tests protect the `None` cases that would otherwise crash real
   use: a task with no due date or no due time can't be compared to one that has
   them, and the sorts, the conflict check, and the display all have to survive it.
   Midnight (`00:00`) has its own test because it is falsy-looking and easy to
   mistake for "no time set".

2) The RAG tests matter because retrieval quality is invisible by inspection —
   the code always returns *something*, and only an assertion says whether it is
   the right thing. Using a fake LLM that records its calls lets me test the
   contract (what evidence was passed, whether an API call happened at all)
   without a key or a network, which is also why the whole suite runs in ~0.1s.

**b. Confidence**

- How confident are you that your scheduler works correctly?

Confident on the paths the tests cover, which is the whole public surface of
`Scheduler` plus the `None`-valued edge cases. Two caveats I would state plainly:
retrieval is only measured against 16 questions I wrote myself, and the live
Gemini calls are not asserted anywhere — every test substitutes a fake client,
though I have run the live path once and captured it in evidence/.

- What edge cases would you test next if you had more time?

Recurring tasks crossing a month or year boundary; two pets whose medication
windows overlap rather than land on the exact same minute (the current conflict
check only catches identical moments); the Streamlit session state surviving a
pet being removed while a task widget is still bound to it; and paraphrased
questions in the retrieval eval, since questions written by the same person who
wrote the notes are an easy test.

---

## 5. The RAG Extension (Final Project)

**a. What I added and why**

The Module 2 scheduler knew *when* every task was due but nothing about pet care
itself. It could not answer "how often should I bathe a dog?" or "I missed a dose,
what now?" — there was no knowledge in the system and no way to ask it anything.
So the extension is a Retrieval-Augmented Generation advisor: a small corpus of
pet care notes in `knowledge/`, keyword retrieval over it in `care_kb.py`, and
grounded generation in `llm_client.py`, joined together in `care_advisor.py`.

The design decision I care most about is that retrieval pulls from **two**
sources, not one. The notes supply general guidance ("walks are 30-60 minutes and
movable"); the live `Owner` and `Scheduler` objects supply this owner's actual day
("Mochi's dose is at 12:00, and something already collides with it"). Neither
alone can answer "when should I fit the walk in?" That is what makes it PawPal's
RAG instead of a generic document search bolted onto the side.

**b. How I used AI on this extension**

I used Claude Code as a pair programmer, with the DocuBot tinker activity as the
structural reference: corpus → index → score → retrieve → grounded prompt → eval
harness. The prompts that worked were the same kind that worked in Module 2 —
specific and scoped to one piece ("why does this question rank the exercise
section above the feeding section?") rather than "build me RAG".

The most useful thing AI did was insist on the evaluation harness *before* the
retrieval was finished. Retrieval quality is invisible when you only eyeball a
few questions; the harness turned "seems fine" into a number that moved when the
code changed.

**c. One helpful AI suggestion**

Chunking the notes by `##` heading instead of retrieving whole files. DocuBot
retrieves entire documents, and my first instinct was to copy that. Splitting
into sections meant a cat feeding question retrieves `FEEDING.md › Cats` — one
focused passage — instead of all 60 lines of the feeding guide, most of which is
about dogs. It improved both the ranking and the size of the prompt.

**d. One flawed AI suggestion**

Query expansion, as first written, made retrieval **worse**, and the bug hid
behind a passing evaluation.

The idea was reasonable: owners ask "how often should I feed them?" without
saying "cat", so the advisor adds the pet's species, name, and medication as extra
retrieval terms. But those terms were weighted the same as the words the owner
actually typed. With two medicated pets in the household, "How many times a day
should I feed my cat?" started ranking `FEEDING.md › Feeding around medication`
and `MEDICATION.md › Heartworm and flea prevention` **above** `FEEDING.md › Cats`.
Context the owner never mentioned was outvoting their actual question.

Worse, the evaluation harness reported a clean 0.93 top-1 the whole time, because
it called `retrieve()` with the bare question — a code path the app never uses.
Two fixes came out of it: boost terms are now discounted (`BOOST_WEIGHT = 0.3`) so
they reorder results without deciding them, and the harness gained a second arm
that evaluates questions *as the app actually issues them*. With the bug
reinstated, the two arms now read 0.93 and 0.64 — the second arm sees it, the
first is blind:

| `BOOST_WEIGHT` | bare arm top-1 | household arm top-1 | off-topic refused |
| --- | --- | --- | --- |
| 1.0 (buggy) | 0.93 | 0.64 | 0/2 |
| 0.3 (current) | 0.93 | 0.93 | 2/2 |

The lesson generalised: **evaluate the path the user actually takes.** A metric on
a path nobody uses is worse than no metric, because it buys false confidence.

Two smaller ones: AI initially put the "refuse when there's no evidence" rule
*only* inside the Gemini client, so the guarantee silently vanished when a
different client was passed in (a test with a fake LLM caught it, and the rule
moved up into `CareAdvisor`); and the stemmer it wrote folded `-ing` and `-s` but
not `-ed`, so "vomited" never matched "vomiting" — which mattered because that
word list drives a safety guardrail.

**e. Verification**

The RAG layer has 48 tests that run without an API key, using a fake LLM that
records what it was asked. That lets me assert the *contract* — that the snippets
handed to the model are exactly the ones retrieved, that the live schedule reaches
the prompt, that an empty retrieval spends no API call — rather than just eyeballing
answers. `python rag_evaluation.py` adds 11 guardrail checks and exits non-zero on
failure.

The most valuable test was one I did not expect to write. Checking a symptom
question revealed that "My cat is vomiting repeatedly, what is wrong?" retrieved
`FEEDING.md › Cats` first (it matches "cat" in the heading), while the vet section
that actually applied scored *below* the evidence floor and was dropped entirely.
A correctly-cited answer from the feeding notes would have been worse than no
answer at all. That produced the escalation guardrail: symptom wording now pulls
safety notes to the front and prefixes a vet referral in every mode.

**f. Limitations**

- **Keyword retrieval, not embeddings.** Matching is lexical, so a question
  phrased entirely differently from the notes ("how much kibble?" when the notes
  say "portion" and "meal") retrieves nothing. The refusal is honest, but it is
  still a miss, and a real user would read it as the app not knowing anything.
- **The corpus is small and hand-written.** Five files, 30 sections. Anything
  outside feeding, medication, exercise, grooming, and vet basics gets refused.
- **Escalation is a keyword list.** It catches "vomiting", "limping", "poison",
  but not "she's just not herself today", which is how owners often describe the
  early signs that matter most.
- **Nothing verifies the model's output at runtime.** The prompt tells it to use
  only the retrieved notes and to cite them, but no code checks that it did. Of
  all the guardrails, the prompt rules are the only ones the model can ignore.
- **Live generation isn't automatically checked.** Every test uses a fake LLM, so
  retrieval, guardrails, and wiring are proven by assertion while the real Gemini
  answers are only confirmed by a captured manual run.
- **The stemmer is crude.** It produces non-words (`dose` → `dos`) and will fold
  unrelated words together. Tolerable, since queries and documents pass through
  the same function, but not linguistically correct.

**g. Future improvements**

1. **A self-check pass.** After generating, ask the model a second time whether
   every claim in its answer is supported by the retrieved snippets, and refuse if
   not. This is the missing guardrail — the only one that would catch the model
   ignoring its instructions.
2. **Embedding-based retrieval, keeping the keyword scorer as a fallback.** Would
   fix the vocabulary-mismatch misses. Worth doing *after* the eval harness is
   trusted, so the change can be measured rather than assumed.
3. **Let the advisor propose schedule edits, not just describe them.** Right now
   it can say the 12:00 collision should move; it cannot move it. Returning a
   structured suggestion the `Scheduler` could apply (with the owner confirming)
   would close the loop between advice and action.
4. **Expand the eval set with paraphrases.** 16 questions written by the same
   person who wrote the notes is an easy test. Paraphrases and owner-style
   phrasing ("is 2 meals enough for a kitten??") would find the real gaps.

---

## 6. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

1) I'm most satisfied that the advisor says "I do not know" instead of making
something up. It would have been easier to let it answer everything, and getting
it to actually refuse took a score floor plus tests to prove it refuses. The vet
escalation is the part I'm most glad I added, since someone asking about a sick
pet needs a vet, not my app.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

1) I'd switch retrieval from keyword matching to embeddings, because right now if
someone asks "how much kibble" and my notes say "portion" it finds nothing. I'd
also let the advisor actually move a task when it spots a conflict instead of just
telling me about it, and I'd make the conflict check look at overlapping time
instead of only the exact same minute.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

1) The biggest thing I learned is that I can't tell if an AI feature works by
reading the code. My retrieval looked fine and my evaluation said 93%, but it was
testing a version of the question my app never actually sends, so it was hiding a
real bug. Once I measured it the way the app really runs, the problem showed up
right away. Testing what the user actually does matters more than testing what's
easy to test.
