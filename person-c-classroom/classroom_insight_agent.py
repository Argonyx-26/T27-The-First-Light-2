"""
classroom_insight_agent.py -- Person C Classroom Intelligence
=============================================================
Aggregates student states into a ranked list of misconceptions.

Input:  list of student state objects (shared student-state contract)
Output: list of { misconception, student_count, topic } sorted by
        student_count DESC, then by (misconception, topic) ASC for
        deterministic tie-breaking.

This agent is fully deterministic and does not call any LLM.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

def aggregate_misconceptions(
    student_states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Aggregate student states into ranked classroom misconceptions.

    Parameters
    ----------
    student_states:
        A list of student state objects following the frozen shared
        student-state contract.  The list is never mutated.

    Returns
    -------
    A list of dicts with exactly three keys:
        misconception  : str
        student_count  : int
        topic          : str
    Sorted by student_count descending.
    Ties broken by (misconception, topic) ascending for determinism.
    """
    if not student_states:
        return []

    # Count students per (misconception, topic) group
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for student in student_states:
        key = (student["misconception"], student["topic"])
        counts[key] += 1

    # Build output list
    result = [
        {
            "misconception": misconception,
            "student_count": count,
            "topic": topic,
        }
        for (misconception, topic), count in counts.items()
    ]

    # Sort: primary -- student_count DESC; secondary -- (misconception, topic) ASC
    result.sort(key=lambda r: (-r["student_count"], r["misconception"], r["topic"]))

    return result


# ---------------------------------------------------------------------------
# Inline test -- runs when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import os
    import sys

    # -- Locate mock data relative to this file ------------------------------
    here = os.path.dirname(os.path.abspath(__file__))
    mock_path = os.path.join(here, "mock_students.json")

    with open(mock_path, encoding="utf-8-sig") as fh:
        student_states = json.load(fh)

    print(f"Loaded {len(student_states)} students from mock_students.json\n")

    # -- Run agent -----------------------------------------------------------
    ranked = aggregate_misconceptions(student_states)

    # -- Print ranked output -------------------------------------------------
    print("Ranked Classroom Misconceptions")
    print("=" * 60)
    for rank, entry in enumerate(ranked, start=1):
        print(
            f"  #{rank:>2}  [{entry['student_count']} students]"
            f"  topic={entry['topic']}"
        )
        print(f"        misconception: {entry['misconception']}")
    print()

    # -- Assertions ----------------------------------------------------------
    errors = []

    # 1. Empty-list contract
    assert aggregate_misconceptions([]) == [], \
        "Empty input should return []"

    # 2. Result is sorted by student_count descending
    counts_seq = [e["student_count"] for e in ranked]
    if counts_seq != sorted(counts_seq, reverse=True):
        errors.append(
            f"Result is NOT sorted descending: {counts_seq}"
        )

    # 3. Top group must have 5 students (matches mock_students.json)
    if not ranked:
        errors.append("Ranked list is empty -- expected at least one group")
    elif ranked[0]["student_count"] != 5:
        errors.append(
            f"Expected top group to have 5 students, "
            f"got {ranked[0]['student_count']}"
        )

    # 4. Determinism: running twice yields identical results
    ranked_again = aggregate_misconceptions(student_states)
    if ranked != ranked_again:
        errors.append("Two identical runs produced different results -- not deterministic")

    # 5. Input list was not mutated
    reloaded = json.loads(open(mock_path, encoding="utf-8-sig").read())
    if student_states != reloaded:
        errors.append("Input list was mutated during aggregation")

    # -- Report --------------------------------------------------------------
    if errors:
        print("ASSERTIONS FAILED:")
        for err in errors:
            print(f"  FAIL  {err}")
        sys.exit(1)
    else:
        print("All assertions PASSED")
        sys.exit(0)
