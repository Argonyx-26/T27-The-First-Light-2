"""
root_cause_agent.py -- Person C Classroom Intelligence
=======================================================
Identifies downstream topics affected by a misconception in a given topic
using reverse traversal of the prerequisite graph.

This agent is fully deterministic and does not call any LLM.
"""

from __future__ import annotations

import os
from typing import Any


# ---------------------------------------------------------------------------
# Constants (frozen by README)
# ---------------------------------------------------------------------------

URGENCY_HIGH_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_reverse_graph(
    prereq_graph: dict[str, Any],
) -> dict[str, list[str]]:
    """
    Build a reverse-dependency map.

    For each topic T, reverse_graph[T] lists every topic that directly
    lists T as one of its prereqs.  This lets us walk *forward* through
    the curriculum to find dependents of a struggling topic.
    """
    reverse: dict[str, list[str]] = {topic: [] for topic in prereq_graph}
    for topic, value in prereq_graph.items():
        for prereq in value.get("prereqs", []):
            if prereq in reverse:
                reverse[prereq].append(topic)
    return reverse


def _find_downstream(
    topic: str,
    reverse_graph: dict[str, list[str]],
) -> list[str]:
    """
    BFS over the reverse graph to find ALL topics that directly or
    indirectly depend on `topic`.

    Returns an alphabetically sorted list that excludes `topic` itself.
    """
    visited: set[str] = set()
    queue: list[str] = list(reverse_graph.get(topic, []))

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for dependent in reverse_graph.get(current, []):
            if dependent not in visited:
                queue.append(dependent)

    visited.discard(topic)
    return sorted(visited)


def _log_unmapped(topic: str, log_path: str) -> None:
    """
    Append `topic` to unmapped_topics.log, creating the file if needed.
    Avoids writing the same topic twice during a single execution.
    """
    existing: set[str] = set()
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            existing = {line.strip() for line in fh if line.strip()}

    if topic not in existing:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(topic + "\n")


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

def analyze_root_cause(
    misconception: str,
    topic: str,
    prereq_graph: dict[str, Any],
    *,
    log_path: str | None = None,
) -> dict[str, Any]:
    """
    Analyze the root-cause downstream impact of a misconception.

    Parameters
    ----------
    misconception:
        The diagnosed misconception string.
    topic:
        The topic where the misconception was observed.
    prereq_graph:
        The prerequisite graph (loaded from shared/prereq_graph.json).
        This dict is never mutated.
    log_path:
        Optional explicit path to unmapped_topics.log.
        Defaults to person-c-classroom/unmapped_topics.log
        relative to this source file.

    Returns
    -------
    {
        "downstream_topics": [str, ...],   -- alphabetically sorted
        "urgency"          : "high" | "low",
        "teacher_explanation": str
    }

    The teacher_explanation references ONLY topics present in
    downstream_topics, as required by the grounding rule.
    """
    # Resolve default log path relative to this file
    if log_path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(here, "unmapped_topics.log")

    # Guard: empty or malformed graph
    if not prereq_graph or not isinstance(prereq_graph, dict):
        return {
            "downstream_topics": [],
            "urgency": "low",
            "teacher_explanation": (
                f"The prerequisite graph is empty or malformed; "
                f"no downstream analysis is available for topic '{topic}'."
            ),
        }

    # Unmapped topic
    if topic not in prereq_graph:
        _log_unmapped(topic, log_path)
        return {
            "downstream_topics": [],
            "urgency": "low",
            "teacher_explanation": (
                f"The topic '{topic}' is not present in the prerequisite "
                f"graph. No downstream impact can be determined."
            ),
        }

    # Build reverse graph and traverse
    reverse_graph = _build_reverse_graph(prereq_graph)
    downstream = _find_downstream(topic, reverse_graph)

    # Urgency uses only the constant -- never the raw number
    urgency = "high" if len(downstream) >= URGENCY_HIGH_THRESHOLD else "low"

    # Teacher explanation -- grounded only in downstream list
    if downstream:
        topics_str = ", ".join(downstream)
        explanation = (
            f"The misconception '{misconception}' in '{topic}' may affect "
            f"later learning of: {topics_str}."
        )
    else:
        explanation = (
            f"The misconception '{misconception}' in '{topic}' has no "
            f"currently mapped downstream topics in the prerequisite graph."
        )

    return {
        "downstream_topics": downstream,
        "urgency": urgency,
        "teacher_explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Smoke test -- runs when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    graph_path = os.path.join(here, "..", "shared", "prereq_graph.json")
    log_path   = os.path.join(here, "unmapped_topics.log")

    with open(graph_path, encoding="utf-8-sig") as fh:
        graph = json.load(fh)

    print("Prerequisite graph loaded successfully.")
    print("Topics: " + str(sorted(graph.keys())))
    print()

    errors: list[str] = []

    # -------------------------------------------------------------------
    # CASE 1 -- fraction_addition: nothing in the graph depends on it
    # -------------------------------------------------------------------
    print("=" * 60)
    print("CASE 1: topic='fraction_addition'")
    r1 = analyze_root_cause(
        misconception="adds denominators directly",
        topic="fraction_addition",
        prereq_graph=graph,
        log_path=log_path,
    )
    print("  downstream_topics : " + str(r1["downstream_topics"]))
    print("  urgency           : " + r1["urgency"])
    print("  teacher_explanation:")
    print("    " + r1["teacher_explanation"])
    print()

    if r1["downstream_topics"] != []:
        errors.append("CASE 1: expected downstream=[], got " + str(r1["downstream_topics"]))
    if r1["urgency"] != "low":
        errors.append("CASE 1: expected urgency=low, got " + r1["urgency"])

    # -------------------------------------------------------------------
    # CASE 2 -- fractions_basic_concept: most topics depend on it
    # -------------------------------------------------------------------
    expected_ds2 = sorted([
        "decimal_multiplication",
        "equivalent_fractions",
        "fraction_addition",
        "fraction_multiplication",
        "percentages",
        "proportions",
        "ratios",
    ])

    print("=" * 60)
    print("CASE 2: topic='fractions_basic_concept'")
    r2 = analyze_root_cause(
        misconception="does not understand part-whole relationship",
        topic="fractions_basic_concept",
        prereq_graph=graph,
        log_path=log_path,
    )
    print("  downstream_topics : " + str(r2["downstream_topics"]))
    print("  urgency           : " + r2["urgency"])
    print("  teacher_explanation:")
    print("    " + r2["teacher_explanation"])
    print()

    if r2["downstream_topics"] != expected_ds2:
        errors.append(
            "CASE 2: downstream mismatch.\n"
            "  expected: " + str(expected_ds2) + "\n"
            "  got     : " + str(r2["downstream_topics"])
        )
    if r2["urgency"] != "high":
        errors.append("CASE 2: expected urgency=high, got " + r2["urgency"])

    # Grounding check: every word in explanation must not introduce alien topics
    for t in r2["downstream_topics"]:
        if t not in r2["teacher_explanation"]:
            errors.append("CASE 2: downstream topic '" + t + "' missing from explanation")

    # -------------------------------------------------------------------
    # CASE 3 -- unmapped topic
    # -------------------------------------------------------------------
    print("=" * 60)
    print("CASE 3: topic='not_a_real_topic'")
    r3 = analyze_root_cause(
        misconception="some misconception",
        topic="not_a_real_topic",
        prereq_graph=graph,
        log_path=log_path,
    )
    print("  downstream_topics : " + str(r3["downstream_topics"]))
    print("  urgency           : " + r3["urgency"])
    print("  teacher_explanation:")
    print("    " + r3["teacher_explanation"])

    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            log_lines = [ln.strip() for ln in fh if ln.strip()]
        print("  unmapped_topics.log contents: " + str(log_lines))
    print()

    if r3["downstream_topics"] != []:
        errors.append("CASE 3: expected downstream=[], got " + str(r3["downstream_topics"]))
    if r3["urgency"] != "low":
        errors.append("CASE 3: expected urgency=low, got " + r3["urgency"])
    if not os.path.exists(log_path):
        errors.append("CASE 3: unmapped_topics.log was not created")
    else:
        with open(log_path, encoding="utf-8") as fh:
            log_text = fh.read()
        if "not_a_real_topic" not in log_text:
            errors.append("CASE 3: 'not_a_real_topic' not found in unmapped_topics.log")

    # Idempotency: calling again must NOT duplicate the log entry
    analyze_root_cause(
        misconception="some misconception",
        topic="not_a_real_topic",
        prereq_graph=graph,
        log_path=log_path,
    )
    with open(log_path, encoding="utf-8") as fh:
        count = sum(1 for ln in fh if ln.strip() == "not_a_real_topic")
    if count > 1:
        errors.append(
            "CASE 3 (idempotency): 'not_a_real_topic' written " + str(count) +
            " times in log (should be 1)"
        )

    # -------------------------------------------------------------------
    # Report
    # -------------------------------------------------------------------
    print("=" * 60)
    if errors:
        print("ASSERTIONS FAILED:")
        for e in errors:
            print("  FAIL  " + e)
        sys.exit(1)
    else:
        print("All assertions PASSED")
        sys.exit(0)
