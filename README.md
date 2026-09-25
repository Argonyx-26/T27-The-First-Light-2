# Classroom Insight — Intelligent Multi-Agent Teaching & Learning Ecosystem

## 1. Project Goal

Build a multi-agent educational system that helps teachers understand classroom-level learning problems.

The system should:

1. Diagnose student misconceptions.
2. Recommend targeted interventions.
3. Verify whether the misconception was actually resolved.
4. Detect false/surface mastery.
5. Aggregate misconceptions across the classroom.
6. Identify prerequisite/root-cause topics.
7. Detect potentially ambiguous assessment questions.
8. Present actionable insights through a teacher-facing dashboard.

The system demonstrates a closed-loop learning process:

```text
diagnose → intervene → verify → classify mastery → retry/flag
```

rather than only:

```text
diagnose → recommend
```

---

# 2. Multi-Agent Architecture

## Person A — Student Assessment & Diagnosis

Responsible for:

* Student-facing quiz.
* Capturing answers.
* Diagnostic analysis.
* Identifying the student's misconception.

Files:

```text
person-a-frontend/
├── quiz-data.json
└── diagnostic_agent.py
```

---

## Person B — Intervention & Verification

Responsible for:

* Recommending learning resources.
* Selecting intervention approaches.
* Generating verification probes.
* Verifying whether learning actually occurred.
* Detecting surface/false mastery.
* Controlling retry/intervention loops.
* Persisting every updated student state.

Files:

```text
person-b-core-agents/
├── recommender_agent.py
├── verification_agent.py
└── loop_controller.py
```

Person B is the ONLY component allowed to write:

```text
shared/live_state.json
```

---

## Person C — Classroom Intelligence

Responsible for:

* Classroom-level misconception aggregation.
* Root-cause analysis.
* Prerequisite dependency analysis.
* Assessment-quality analysis.
* Teacher-facing dashboard.

Files:

```text
person-c-classroom/
├── classroom_insight_agent.py
├── root_cause_agent.py
├── assessment_quality_agent.py
├── dashboard.html
└── mock_students.json
```

Person C reads shared state but does NOT modify it.

---

# 3. Shared Student State Contract

The shared student state is stored in:

```text
shared/live_state.json
```

Person B writes this file.

Person C reads this file.

Each student state uses the following contract:

```json
{
  "student_id": "s1",
  "topic": "fractions",
  "misconception": "adds denominators directly",
  "status": "diagnosed",
  "attempts": 1,
  "resource_given": "string",
  "approach_used": "worked_example",
  "previous_approaches": [],
  "verification_result": "pending",
  "flagged_false_mastery": false
}
```

## Required fields

### student_id

Unique student identifier.

### topic

Current learning topic.

### misconception

The diagnosed misconception.

### status

Current state in the intervention/verification lifecycle.

### attempts

Number of intervention attempts.

### resource_given

A flat string describing the resource/intervention given to the student.

Example:

```text
"Worked example showing how to find a common denominator before addition."
```

It MUST NOT be a nested object.

Incorrect:

```json
{
  "resource_given": {
    "explanation": "...",
    "approach_used": "...",
    "practice_hint": "..."
  }
}
```

Correct:

```json
{
  "resource_given": "Worked example showing how to find a common denominator before addition.",
  "approach_used": "worked_example"
}
```

### approach_used

The most recently used intervention approach.

Allowed values:

```text
worked_example
analogy
visual_description
direct_explanation
```

Use underscores exactly as shown.

Do NOT use:

```text
worked-example
direct-explanation
```

### previous_approaches

Persistent list of approaches already used for the current misconception/intervention loop.

Example:

```json
"previous_approaches": [
  "worked_example",
  "visual_description"
]
```

This allows the recommender to avoid repeating an intervention approach after an unresolved result.

The most recent approach must also be stored in:

```text
approach_used
```

### verification_result

A flat enum string.

Allowed values:

```text
true_mastery
surface_mastery
unresolved
pending
```

Do NOT store an object such as:

```json
{
  "status": "true_mastery",
  "reasoning": "..."
}
```

Verification reasoning is not part of the shared student-state contract.

If reasoning is required for debugging or demonstration, it may be kept locally by the verification agent or in a separate non-contract log.

### flagged_false_mastery

Boolean.

```text
true
```

ONLY when:

```text
verification_result == "surface_mastery"
```

The flag is persistent.

If a student receives:

```text
verification_result = "surface_mastery"
```

then:

```text
flagged_false_mastery = true
```

must remain true even after:

```text
status = "verified"
```

This ensures teachers can still identify students who demonstrated surface mastery.

---

# 4. Allowed Status Values

The shared state may use only:

```text
diagnosed
intervened
verifying
verified
escalated
```

## Status lifecycle

### Initial diagnosis

```text
diagnosed
```

### Intervention delivered

```text
diagnosed
    ↓
intervened
```

### Verification probe is being administered/scored

```text
intervened
    ↓
verifying
```

### Verification outcome

If true mastery:

```text
verifying
    ↓
verified
```

If surface mastery:

```text
verifying
    ↓
verified
```

with:

```text
flagged_false_mastery = true
```

If unresolved:

```text
verifying
    ↓
escalated
```

### Retry

`escalated` routes back through the recommender.

```text
escalated
    ↓
recommender
    ↓
different approach
    ↓
intervened
    ↓
verifying
```

The retry MUST NOT reuse an approach already present in:

```text
previous_approaches
```

unless all available approaches have already been exhausted.

---

# 5. Verification Model

Verification should not simply repeat the same question.

The verification progression is:

```text
near_transfer
      ↓
far_transfer
      ↓
novel_context
```

These probes test whether the student can generalize the concept rather than merely recognize the original question pattern.

## verification_probes

Verification probes are generated and used internally by:

```text
verification_agent.py
```

They are **ephemeral** and are NOT part of the shared student-state contract.

They may exist in memory/local variables during verification.

Do NOT add:

```text
verification_probes
```

to `shared/live_state.json`.

---

# 6. Verification Outcomes

## true_mastery

The student successfully generalizes the concept across the verification progression.

State transition:

```text
verifying
    ↓
verified
```

---

## surface_mastery

The student succeeds in a familiar form but fails to generalize sufficiently.

State transition:

```text
verifying
    ↓
verified
```

AND:

```text
flagged_false_mastery = true
```

The student advances, but the teacher dashboard retains the persistent false-mastery flag.

---

## unresolved

The misconception remains.

State transition:

```text
verifying
    ↓
escalated
```

The loop controller then requests another intervention using a different approach.

---

# 7. Intervention Approach Selection

Available approaches:

```text
worked_example
analogy
visual_description
direct_explanation
```

The recommender must inspect:

```text
previous_approaches
```

before selecting an approach.

Example:

```json
"previous_approaches": [
  "worked_example"
]
```

The next recommendation should not use:

```text
worked_example
```

again.

After selecting a new approach:

1. Add it to `previous_approaches`.
2. Set `approach_used` to that approach.
3. Generate the corresponding `resource_given`.
4. Increment `attempts` when a new intervention attempt begins.

---

# 8. Loop Controller Responsibilities

File:

```text
person-b-core-agents/loop_controller.py
```

The loop controller owns the state lifecycle.

It must:

1. Read the current student state.
2. Decide the next action.
3. Call the recommender when intervention is required.
4. Call the verification agent when verification is required.
5. Update the student state.
6. Apply the correct status transition.
7. Preserve `flagged_false_mastery`.
8. Maintain `previous_approaches`.
9. Persist the updated state to `shared/live_state.json`.

## Persistence rule

After every successful `advance()` call, the loop controller MUST write the updated student state into:

```text
shared/live_state.json
```

This means the live state is updated after every lifecycle transition rather than only at the end of the complete learning loop.

Person C can therefore observe the current state by reading:

```text
shared/live_state.json
```

---

# 9. Example Loop

Example unresolved case:

```text
diagnosed
   ↓
recommender
   ↓
intervened
   ↓
verifying
   ↓
verification_result = unresolved
   ↓
escalated
   ↓
recommender
   ↓
different approach
   ↓
intervened
   ↓
verifying
   ↓
verification_result = true_mastery
   ↓
verified
```

Example surface-mastery case:

```text
diagnosed
   ↓
recommender
   ↓
intervened
   ↓
verifying
   ↓
verification_result = surface_mastery
   ↓
verified
   +
flagged_false_mastery = true
```

---

# 10. Prerequisite Graph

Person C owns:

```text
shared/prereq_graph.json
```

The graph uses topic names as top-level keys.

Example:

```json
{
  "fractions_basic_concept": {
    "prereqs": []
  },
  "equivalent_fractions": {
    "prereqs": [
      "fractions_basic_concept"
    ]
  },
  "fraction_addition": {
    "prereqs": [
      "fractions_basic_concept",
      "equivalent_fractions"
    ]
  }
}
```

The graph should contain approximately 6–8 topics.

Root-cause analysis determines downstream topics through reverse traversal.

Example:

```text
fractions_basic_concept
        ↓
equivalent_fractions
        ↓
fraction_addition
```

If a student struggles with:

```text
fractions_basic_concept
```

the system identifies downstream topics that may also be affected.

---

# 11. Classroom Insight Agent

File:

```text
person-c-classroom/classroom_insight_agent.py
```

### Input

A list of student state objects.

### Output

```python
[
    {
        "misconception": str,
        "student_count": int,
        "topic": str
    }
]
```

Results must be sorted by:

```text
student_count descending
```

This identifies the most common misconceptions in the classroom.

---

# 12. Root Cause Agent

File:

```text
person-c-classroom/root_cause_agent.py
```

### Input

One:

```text
misconception/topic pair
```

plus:

```text
prereq_graph.json
```

### Output

```python
{
    "downstream_topics": [],
    "urgency": "high",
    "teacher_explanation": "..."
}
```

## Fixed threshold

```python
URGENCY_HIGH_THRESHOLD = 2
```

High urgency:

```text
downstream_topics >= 2
```

Low urgency:

```text
downstream_topics < 2
```

### Grounding Rule

`teacher_explanation` may ONLY mention topics contained in:

```text
downstream_topics
```

The explanation must not invent unrelated dependencies.

If a topic cannot be mapped to the graph:

```text
unmapped_topics.log
```

should record it rather than crashing the system.

---

# 13. Assessment Quality Agent

File:

```text
person-c-classroom/assessment_quality_agent.py
```

The agent analyzes answer distributions for a question.

## Fixed constants

```python
SAME_WRONG_ANSWER_THRESHOLD = 0.60
MIN_STUDENTS_FOR_FLAG = 3
```

A question becomes a candidate for ambiguity analysis when:

```text
>= 60% of eligible students
```

give the same wrong answer AND:

```text
at least 3 students
```

are represented.

### Output

```python
{
    "question_id": str,
    "flagged": bool,
    "possibly_ambiguous_question": bool,
    "reasoning": str
}
```

`possibly_ambiguous_question` is only evaluated when:

```text
flagged == true
```

The analysis must be grounded in the actual answer distribution.

---

# 14. Teacher Dashboard

File:

```text
person-c-classroom/dashboard.html
```

The dashboard must display three major sections.

## Section 1 — Ranked Classroom Misconceptions

Display:

```text
misconception
student_count
topic
urgency
teacher_explanation
```

Rank by:

```text
student_count descending
```

---

## Section 2 — False Mastery Students

Display every student where:

```text
flagged_false_mastery == true
```

This must happen regardless of the student's current status.

For example:

```text
status = verified
flagged_false_mastery = true
```

must still appear.

---

## Section 3 — Potentially Ambiguous Questions

Display assessment-quality results where:

```text
possibly_ambiguous_question == true
```

---

# 15. Person C Mock Data

Before full integration:

```text
person-c-classroom/mock_students.json
```

may contain:

```text
10–15 students
```

Each record must match the shared student-state contract.

The mock data should include:

* repeated misconceptions
* different topics
* different statuses
* different attempt counts
* true mastery
* unresolved cases
* surface mastery
* at least one flagged false-mastery case
* multiple intervention approaches
* examples with `previous_approaches`

---

# 16. Ownership Rules

### Person A

May modify:

```text
person-a-frontend/
```

### Person B

May modify:

```text
person-b-core-agents/
```

and is the only writer of:

```text
shared/live_state.json
```

### Person C

May modify:

```text
person-c-classroom/
```

and authors:

```text
shared/prereq_graph.json
```

Person C reads:

```text
shared/live_state.json
```

but MUST NOT modify it.

---

# 17. Shared File Rules

The following are shared contract/integration files:

```text
contract/schema.json
shared/prereq_graph.json
shared/mock-data.json
shared/live_state.json
```

Changes to shared contracts should happen only at agreed checkpoints.

Do not silently change a shared field or enum during implementation.

---

# 18. Naming Rules

Use:

```text
snake_case
```

Use the exact filenames specified in this README.

Do not rename files.

Do not abbreviate component names.

Enum values must match this README character-for-character.

---

# 19. Hackathon Demonstration Flow

The final demonstration should show:

```text
Student answers
      ↓
Diagnostic Agent
      ↓
Misconception detected
      ↓
Recommendation
      ↓
Intervention
      ↓
Verification
      ↓
true_mastery / surface_mastery / unresolved
      ↓
Loop Controller
      ↓
shared/live_state.json
      ↓
Classroom Insight
      ↓
Root Cause + Assessment Quality
      ↓
Teacher Dashboard
```

The key differentiating capability is:

```text
diagnose
   ↓
intervene
   ↓
verify
   ↓
detect surface mastery
   ↓
retry or flag
```

rather than simply:

```text
diagnose
   ↓
recommend
```

---

# 20. Contract Decisions — Frozen Before Implementation

The following decisions resolve earlier specification mismatches.

| Issue                      | Final decision                                            |
| -------------------------- | --------------------------------------------------------- |
| `resource_given` structure | Flat string                                               |
| `approach_used` structure  | Top-level enum field                                      |
| Approach naming            | Underscores                                               |
| `verification_result`      | Flat enum string                                          |
| Verification reasoning     | Not part of shared state                                  |
| False mastery status       | `verified` + persistent `flagged_false_mastery=true`      |
| Retry status               | `escalated`                                               |
| `verifying` state          | Explicit state between intervention and result            |
| `verification_probes`      | Ephemeral inside verification agent; not shared state     |
| Approach history           | Persisted in `previous_approaches`                        |
| Live-state persistence     | Loop controller writes after every successful `advance()` |

These decisions are authoritative for implementation.

No agent should introduce a conflicting representation.
