"""
assessment_quality_agent.py -- Classroom Insights
==============================================================
Analyzes one question's answer distribution to detect potentially
ambiguous assessment questions based on a response-concentration signal.

This agent is fully deterministic and does not call any LLM.

Algorithm
---------
A question is flagged for teacher review when the most-selected answer
option accounts for >= SAME_WRONG_ANSWER_THRESHOLD of all responses AND
at least MIN_STUDENTS_FOR_FLAG total responses exist.

High concentration on a single option may indicate that the question
wording is ambiguous, leading many students to the same interpretation --
even if that interpretation differs from the intended correct answer.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Constants (frozen by README)
# ---------------------------------------------------------------------------

SAME_WRONG_ANSWER_THRESHOLD = 0.60
MIN_STUDENTS_FOR_FLAG = 3

# The set of fields every returned dict must contain (used in tests)
_OUTPUT_FIELDS = {"question_id", "flagged", "possibly_ambiguous_question", "reasoning"}


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

def analyze_question_quality(
    question_id: str,
    answer_distribution: dict[str, int],
) -> dict[str, Any]:
    """
    Analyze one question's answer distribution for ambiguity signals.

    Parameters
    ----------
    question_id:
        Identifier for the question being analyzed.
    answer_distribution:
        Mapping of answer-option label -> number of students selecting it.
        Example: {"A": 2, "B": 8, "C": 7, "D": 3}
        The dict is never mutated.

    Returns
    -------
    {
        "question_id"              : str,
        "flagged"                  : bool,
        "possibly_ambiguous_question": bool,
        "reasoning"                : str
    }

    Flagging rule
    -------------
    The question is flagged when ALL of the following hold:
      1. total responses >= MIN_STUDENTS_FOR_FLAG
      2. The most-selected answer option accounts for
         >= SAME_WRONG_ANSWER_THRESHOLD of all responses.

    Note: `possibly_ambiguous_question` is always False when `flagged`
    is False, as required by the contract.
    """
    # Guard: empty distribution
    if not answer_distribution:
        return {
            "question_id": question_id,
            "flagged": False,
            "possibly_ambiguous_question": False,
            "reasoning": (
                "No answer data was provided for this question; "
                "ambiguity analysis cannot be performed."
            ),
        }

    total = sum(answer_distribution.values())

    # Guard: insufficient responses
    if total < MIN_STUDENTS_FOR_FLAG:
        return {
            "question_id": question_id,
            "flagged": False,
            "possibly_ambiguous_question": False,
            "reasoning": (
                f"Only {total} response(s) recorded for question "
                f"'{question_id}'; at least {MIN_STUDENTS_FOR_FLAG} "
                f"responses are required before flagging."
            ),
        }

    # Find the most-selected answer and its proportion of all responses
    top_option = max(answer_distribution, key=lambda opt: answer_distribution[opt])
    top_count = answer_distribution[top_option]
    top_proportion = top_count / total

    # Apply threshold
    if top_proportion >= SAME_WRONG_ANSWER_THRESHOLD:
        pct = round(top_proportion * 100, 1)
        return {
            "question_id": question_id,
            "flagged": True,
            "possibly_ambiguous_question": True,
            "reasoning": (
                f"Option '{top_option}' was selected by {top_count} of "
                f"{total} students ({pct}%), which meets or exceeds the "
                f"{int(SAME_WRONG_ANSWER_THRESHOLD * 100)}% concentration "
                f"threshold. A substantial number of students converging on "
                f"the same answer may indicate a potentially ambiguous "
                f"question and warrants teacher review."
            ),
        }

    # Below threshold -- not flagged
    pct = round(top_proportion * 100, 1)
    return {
        "question_id": question_id,
        "flagged": False,
        "possibly_ambiguous_question": False,
        "reasoning": (
            f"The observed answer distribution for question '{question_id}' "
            f"does not meet the ambiguity threshold: the most-selected "
            f"option ('{top_option}') accounts for {pct}% of responses, "
            f"below the {int(SAME_WRONG_ANSWER_THRESHOLD * 100)}% threshold."
        ),
    }


# ---------------------------------------------------------------------------
# Inline test -- runs when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import copy
    import sys

    errors: list[str] = []

    def check(label: str, result: dict, *, flagged: bool, ambiguous: bool) -> None:
        """Assert flagged and possibly_ambiguous_question match expectations."""
        if result["flagged"] != flagged:
            errors.append(
                label + ": expected flagged=" + str(flagged) +
                ", got " + str(result["flagged"])
            )
        if result["possibly_ambiguous_question"] != ambiguous:
            errors.append(
                label + ": expected possibly_ambiguous_question=" + str(ambiguous) +
                ", got " + str(result["possibly_ambiguous_question"])
            )
        # Contract: possibly_ambiguous_question must be False when flagged is False
        if not result["flagged"] and result["possibly_ambiguous_question"]:
            errors.append(
                label + ": possibly_ambiguous_question must be False when flagged is False"
            )
        # Contract: exactly the four required fields
        if set(result.keys()) != _OUTPUT_FIELDS:
            errors.append(
                label + ": output fields mismatch -- got " + str(set(result.keys()))
            )

    # -----------------------------------------------------------------------
    # CASE 1 -- flagged: option B attracts 60% of all responses
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 1: q1 -- one option attracts 60% (expect flagged=True)")
    dist1 = {"A": 1, "B": 6, "C": 1, "D": 2}
    snapshot1 = copy.deepcopy(dist1)
    r1 = analyze_question_quality("q1", dist1)
    print("  flagged                    : " + str(r1["flagged"]))
    print("  possibly_ambiguous_question: " + str(r1["possibly_ambiguous_question"]))
    print("  reasoning: " + r1["reasoning"])
    check("CASE 1", r1, flagged=True, ambiguous=True)
    # Input mutation check
    if dist1 != snapshot1:
        errors.append("CASE 1: input dict was mutated")
    print()

    # -----------------------------------------------------------------------
    # CASE 2 -- not flagged: spread distribution, no option >= 60%
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 2: q2 -- spread distribution (expect flagged=False)")
    dist2 = {"A": 2, "B": 3, "C": 3, "D": 2}
    snapshot2 = copy.deepcopy(dist2)
    r2 = analyze_question_quality("q2", dist2)
    print("  flagged                    : " + str(r2["flagged"]))
    print("  possibly_ambiguous_question: " + str(r2["possibly_ambiguous_question"]))
    print("  reasoning: " + r2["reasoning"])
    check("CASE 2", r2, flagged=False, ambiguous=False)
    if dist2 != snapshot2:
        errors.append("CASE 2: input dict was mutated")
    print()

    # -----------------------------------------------------------------------
    # CASE 3 -- insufficient responses (total < MIN_STUDENTS_FOR_FLAG)
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 3: q3 -- only 2 responses (expect flagged=False)")
    dist3 = {"A": 1, "B": 1}
    snapshot3 = copy.deepcopy(dist3)
    r3 = analyze_question_quality("q3", dist3)
    print("  flagged                    : " + str(r3["flagged"]))
    print("  possibly_ambiguous_question: " + str(r3["possibly_ambiguous_question"]))
    print("  reasoning: " + r3["reasoning"])
    check("CASE 3", r3, flagged=False, ambiguous=False)
    if dist3 != snapshot3:
        errors.append("CASE 3: input dict was mutated")
    print()

    # -----------------------------------------------------------------------
    # CASE 4 -- empty distribution
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 4: q4 -- empty distribution (expect flagged=False)")
    dist4: dict[str, int] = {}
    r4 = analyze_question_quality("q4", dist4)
    print("  flagged                    : " + str(r4["flagged"]))
    print("  possibly_ambiguous_question: " + str(r4["possibly_ambiguous_question"]))
    print("  reasoning: " + r4["reasoning"])
    check("CASE 4", r4, flagged=False, ambiguous=False)
    print()

    # -----------------------------------------------------------------------
    # CASE 5 -- boundary: exactly at threshold (60.0%), 5 students
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 5: q5 -- exactly at threshold 3/5=60% (expect flagged=True)")
    dist5 = {"A": 3, "B": 1, "C": 1}
    r5 = analyze_question_quality("q5", dist5)
    print("  flagged                    : " + str(r5["flagged"]))
    print("  possibly_ambiguous_question: " + str(r5["possibly_ambiguous_question"]))
    print("  reasoning: " + r5["reasoning"])
    check("CASE 5", r5, flagged=True, ambiguous=True)
    print()

    # -----------------------------------------------------------------------
    # CASE 6 -- just below threshold: 2/4=50%
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("CASE 6: q6 -- just below threshold 2/4=50% (expect flagged=False)")
    dist6 = {"A": 2, "B": 1, "C": 1}
    r6 = analyze_question_quality("q6", dist6)
    print("  flagged                    : " + str(r6["flagged"]))
    print("  possibly_ambiguous_question: " + str(r6["possibly_ambiguous_question"]))
    print("  reasoning: " + r6["reasoning"])
    check("CASE 6", r6, flagged=False, ambiguous=False)
    print()

    # -----------------------------------------------------------------------
    # Determinism: two calls with identical input produce identical output
    # -----------------------------------------------------------------------
    r1a = analyze_question_quality("q1", {"A": 1, "B": 6, "C": 1, "D": 2})
    r1b = analyze_question_quality("q1", {"A": 1, "B": 6, "C": 1, "D": 2})
    if r1a != r1b:
        errors.append("Determinism: two identical calls produced different results")

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print("=" * 60)
    if errors:
        print("ASSERTIONS FAILED:")
        for e in errors:
            print("  FAIL  " + e)
        sys.exit(1)
    else:
        print("All assertions PASSED")
        sys.exit(0)
