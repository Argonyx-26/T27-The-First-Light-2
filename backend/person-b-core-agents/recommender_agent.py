"""
recommender_agent.py -- Personalized Practice: Intervention & Verification
=============================================================
Selects a deterministic intervention approach and generates a concrete
resource description for a student based on their current misconception,
topic, and intervention history.

Contract reference: contract/schema.json
  - approach_used  : ApproachUsed enum (worked_example | analogy |
                     visual_description | direct_explanation)
  - resource_given : flat string -- never a nested object
  - previous_approaches must be inspected before selecting a new approach
    so that no approach is repeated unless all four are exhausted.

This agent is fully deterministic. It makes no LLM or API calls.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Frozen approach enum (mirrors contract/schema.json ApproachUsed)
# ---------------------------------------------------------------------------

APPROACHES: list[str] = [
    "worked_example",
    "analogy",
    "visual_description",
    "direct_explanation",
]

# ---------------------------------------------------------------------------
# Misconception-aware preferred approach ordering
#
# Keys are lowercase substrings that appear in the misconception string.
# The value is an ordered list of approaches, most-preferred first.
# The fallback order is used when no keyword matches.
# ---------------------------------------------------------------------------

_PREFERRED_ORDER: list[tuple[str, list[str]]] = [
    # Fraction addition -- show the mechanics step-by-step first
    ("adds denominator",        ["worked_example", "visual_description", "analogy", "direct_explanation"]),
    ("add denominator",         ["worked_example", "visual_description", "analogy", "direct_explanation"]),
    # Decimal / place-value errors -- spatial/visual representation helps most
    ("decimal point",           ["visual_description", "analogy", "worked_example", "direct_explanation"]),
    ("place value",             ["visual_description", "analogy", "worked_example", "direct_explanation"]),
    ("powers of ten",           ["visual_description", "analogy", "worked_example", "direct_explanation"]),
    ("multiply",                ["visual_description", "worked_example", "direct_explanation", "analogy"]),
    # Whole-number / mixed-fraction confusion -- analogy anchors intuition
    ("whole number",            ["analogy", "worked_example", "direct_explanation", "visual_description"]),
    ("mixed fraction",          ["analogy", "worked_example", "direct_explanation", "visual_description"]),
    ("mixed number",            ["analogy", "worked_example", "direct_explanation", "visual_description"]),
    # Fraction concept / equivalence
    ("equivalent fraction",     ["visual_description", "analogy", "worked_example", "direct_explanation"]),
    ("fraction",                ["worked_example", "analogy", "visual_description", "direct_explanation"]),
    # Ratio / proportion
    ("ratio",                   ["analogy", "visual_description", "worked_example", "direct_explanation"]),
    ("proportion",              ["analogy", "visual_description", "worked_example", "direct_explanation"]),
    # Percentage
    ("percent",                 ["worked_example", "visual_description", "analogy", "direct_explanation"]),
]

# Default order for completely unrecognised misconceptions
_FALLBACK_ORDER: list[str] = [
    "direct_explanation",
    "worked_example",
    "analogy",
    "visual_description",
]


# ---------------------------------------------------------------------------
# Resource templates
#
# Each entry is a (misconception_keyword, approach) -> resource string.
# For unmatched combinations a general template is applied.
# ---------------------------------------------------------------------------

_RESOURCE_TEMPLATES: dict[tuple[str, str], str] = {
    # adds denominators directly
    ("adds denominator", "worked_example"): (
        "Worked example: to add 1/3 + 1/4, first find the least common denominator (12). "
        "Rewrite as 4/12 + 3/12, then add only the numerators to get 7/12. "
        "The denominator (12) stays the same throughout."
    ),
    ("adds denominator", "visual_description"): (
        "Visual: draw two fraction bars of different widths. Show that you cannot combine "
        "differently-sized pieces directly. Redraw both bars divided into equal-sized pieces "
        "(common denominator) before shading and counting the total."
    ),
    ("adds denominator", "analogy"): (
        "Analogy: imagine combining two bags of coins — one with quarters and one with dimes. "
        "You cannot simply count 'coins' because each coin has a different value. "
        "You must convert both to the same unit (cents) before adding."
    ),
    ("adds denominator", "direct_explanation"): (
        "Direct explanation: the denominator names the size of each fractional piece. "
        "Adding fractions with different denominators is like adding apples to oranges — "
        "you must first express both fractions in terms of the same piece size "
        "(the common denominator), then add only the numerators."
    ),

    # adds denominator (alternate phrasing)
    ("add denominator", "worked_example"): (
        "Worked example: to add 2/5 + 1/3, find the LCM of 5 and 3, which is 15. "
        "Rewrite as 6/15 + 5/15 = 11/15. Never add the denominators."
    ),
    ("add denominator", "visual_description"): (
        "Visual: use fraction strips. Align strips for 2/5 and 1/3. Notice they don't fit "
        "together cleanly. Switch to fifteenths strips to show how equal-sized pieces can be combined."
    ),
    ("add denominator", "analogy"): (
        "Analogy: adding 2/5 + 1/3 directly is like saying 2 slices of a 5-slice pizza "
        "plus 1 slice of a 3-slice pizza equals 3 slices of an 8-slice pizza. "
        "That changes the pizza size — and loses meaning."
    ),
    ("add denominator", "direct_explanation"): (
        "Direct explanation: denominators represent slice sizes. They never change just "
        "because you added fractions. Always find a common denominator first."
    ),

    # decimal point direction
    ("decimal point", "visual_description"): (
        "Visual: draw a place-value chart (thousands | hundreds | tens | ones | tenths | hundredths). "
        "Start with 3.7. Multiplying by 10 moves every digit one column LEFT (to a larger place value), "
        "giving 37.0 — the decimal point appears to shift right."
    ),
    ("decimal point", "analogy"): (
        "Analogy: think of the decimal point as a fixed marker on a ruler. "
        "When you multiply by 10 you 'zoom out' — everything becomes 10× bigger, "
        "so the number moves to the left of the decimal, not to the right."
    ),
    ("decimal point", "worked_example"): (
        "Worked example: 4.56 × 10 = 45.6. "
        "Each digit shifts one place to the left: 4 (ones) becomes 4 (tens); "
        "5 (tenths) becomes 5 (ones); 6 (hundredths) becomes 6 (tenths). "
        "The decimal point moves one position to the right in appearance."
    ),
    ("decimal point", "direct_explanation"): (
        "Direct explanation: multiplying by 10 increases the value tenfold. "
        "That means digits move to higher place values (left). "
        "The decimal point shifts RIGHT when multiplying by 10, LEFT when dividing."
    ),

    # powers of ten
    ("powers of ten", "visual_description"): (
        "Visual: use a place-value chart. For each factor of 10 you multiply by, "
        "shift every digit one column to the left. Show 0.05 × 100 = 5.0 by moving digits two columns left."
    ),
    ("powers of ten", "analogy"): (
        "Analogy: think of powers of ten as a zoom level on a map. "
        "Multiplying by 10 zooms out one level — everything gets bigger, so digits shift to larger places."
    ),
    ("powers of ten", "worked_example"): (
        "Worked example: 0.007 × 1000. Move the decimal three places right: 0.007 → 0.07 → 0.7 → 7. "
        "Each multiplication by 10 moves the decimal one place to the right."
    ),
    ("powers of ten", "direct_explanation"): (
        "Direct explanation: multiplying by 10^n shifts the decimal n places to the right "
        "(the value grows). Dividing by 10^n shifts it n places to the left (the value shrinks)."
    ),

    # whole number / mixed fractions
    ("whole number", "analogy"): (
        "Analogy: a mixed number is like a box of apples with some loose ones beside it. "
        "When you add two boxes, count the full boxes separately from the loose apples, "
        "then combine. Never ignore the full boxes."
    ),
    ("whole number", "worked_example"): (
        "Worked example: 2 3/4 + 1 1/2. Add whole numbers: 2 + 1 = 3. "
        "Add fractions: 3/4 + 2/4 = 5/4 = 1 1/4. "
        "Combine: 3 + 1 1/4 = 4 1/4."
    ),
    ("whole number", "direct_explanation"): (
        "Direct explanation: a mixed number has two distinct parts — the integer part and "
        "the fractional part. Both parts must be included in any arithmetic operation. "
        "Dropping the integer part changes the value of the number entirely."
    ),
    ("whole number", "visual_description"): (
        "Visual: draw number lines marking both the integer jumps and the fractional remainder. "
        "Show 2 3/4 and 1 1/2 as two separate segments, then combine them segment by segment."
    ),

    # equivalent fractions
    ("equivalent fraction", "visual_description"): (
        "Visual: draw fraction bars for 1/2 and 2/4 and 4/8. Show they cover the same length "
        "even though they look different. Equivalent fractions are the same amount expressed differently."
    ),
    ("equivalent fraction", "analogy"): (
        "Analogy: 1/2 of a pizza equals 2/4 of the same pizza — you just cut it differently. "
        "The fraction changes its appearance but not its value."
    ),
    ("equivalent fraction", "worked_example"): (
        "Worked example: to find a fraction equivalent to 3/5, multiply top and bottom by the same number. "
        "3/5 × 2/2 = 6/10. Check: 6 ÷ 10 = 0.6 and 3 ÷ 5 = 0.6. They are equal."
    ),
    ("equivalent fraction", "direct_explanation"): (
        "Direct explanation: multiplying or dividing both numerator and denominator by the same "
        "non-zero number preserves the fraction's value, because you are multiplying by 1 in disguise."
    ),

    # ratio
    ("ratio", "analogy"): (
        "Analogy: a ratio is a recipe. If a recipe calls for 2 parts flour to 1 part sugar, "
        "doubling the batch means 4 parts flour to 2 parts sugar — the ratio stays the same."
    ),
    ("ratio", "visual_description"): (
        "Visual: draw two bars side by side representing the quantities in the ratio. "
        "Show that scaling both bars by the same factor preserves the ratio."
    ),
    ("ratio", "worked_example"): (
        "Worked example: the ratio of boys to girls is 3:5. "
        "If there are 12 boys, then girls = (5/3) × 12 = 20. "
        "Always keep the same multiplier for both parts."
    ),
    ("ratio", "direct_explanation"): (
        "Direct explanation: a ratio compares two quantities multiplicatively, not additively. "
        "Changing one side requires scaling the other by the same factor to preserve the relationship."
    ),

    # proportion
    ("proportion", "analogy"): (
        "Analogy: if 3 workers take 6 hours to paint a fence, "
        "6 workers (double) take 3 hours (half) — inverse proportion. "
        "Always ask: does doubling one quantity double or halve the other?"
    ),
    ("proportion", "visual_description"): (
        "Visual: draw a double number line showing one quantity on top and the other below. "
        "Equal scaling on both lines represents a direct proportion."
    ),
    ("proportion", "worked_example"): (
        "Worked example (direct proportion): if 4 tickets cost £10, then 10 tickets cost £25. "
        "Unit rate: £10 ÷ 4 = £2.50 per ticket. 10 × £2.50 = £25."
    ),
    ("proportion", "direct_explanation"): (
        "Direct explanation: in a direct proportion, the ratio between two quantities is constant. "
        "Cross-multiply to solve: a/b = c/d means a × d = b × c."
    ),

    # percent
    ("percent", "worked_example"): (
        "Worked example: 30% of 250. Convert: 30% = 30/100 = 0.3. "
        "Multiply: 0.3 × 250 = 75. "
        "Always convert the percentage to a decimal or fraction before calculating."
    ),
    ("percent", "visual_description"): (
        "Visual: draw a bar representing 100%. Shade 30 of the 100 equal sections. "
        "That shaded portion of the whole bar represents the answer."
    ),
    ("percent", "analogy"): (
        "Analogy: 'percent' means 'per hundred'. Think of it as a pizza cut into exactly 100 slices. "
        "30% means you take 30 of those slices."
    ),
    ("percent", "direct_explanation"): (
        "Direct explanation: percentage is a ratio with denominator 100. "
        "To find p% of N, compute (p/100) × N. Never add the percentage value directly to the number."
    ),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_preferred_order(misconception: str) -> list[str]:
    """
    Return the preferred approach order for a given misconception string.
    Matches on lowercase substrings; falls back to _FALLBACK_ORDER.
    """
    mc_lower = misconception.lower()
    for keyword, order in _PREFERRED_ORDER:
        if keyword in mc_lower:
            return order
    return _FALLBACK_ORDER


def _select_approach(
    preferred_order: list[str],
    previous_approaches: list[str],
) -> str:
    """
    Select the first approach in preferred_order that is NOT already in
    previous_approaches.  If all four approaches are exhausted, return the
    first entry of preferred_order (loop restarts deterministically).
    """
    used = set(previous_approaches)
    for approach in preferred_order:
        if approach not in used:
            return approach
    # All approaches exhausted — restart from the top of preferred_order
    return preferred_order[0]


def _build_resource(misconception: str, approach: str) -> str:
    """
    Look up a specific resource template for (misconception_keyword, approach).
    Falls back to a general template if no specific match exists.
    """
    mc_lower = misconception.lower()
    # Try each keyword in order; use the first match
    for keyword, _ in _PREFERRED_ORDER:
        if keyword in mc_lower:
            resource = _RESOURCE_TEMPLATES.get((keyword, approach))
            if resource:
                return resource
            break  # keyword matched but no template for this approach -- use fallback

    # General fallback template
    approach_labels = {
        "worked_example":    "a step-by-step worked example",
        "analogy":           "an analogy",
        "visual_description":"a visual/diagrammatic description",
        "direct_explanation":"a direct conceptual explanation",
    }
    label = approach_labels.get(approach, approach)
    return (
        f"Intervention using {label} for the misconception: '{misconception}'. "
        f"Focus on the core concept and ensure the student can apply it in a new context."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_intervention(student_state: dict[str, Any]) -> dict[str, str]:
    """
    Recommend a deterministic intervention for a student.

    Parameters
    ----------
    student_state:
        A StudentState-compatible dict.  Only the following fields are read:
          - misconception       (str)
          - topic               (str)  -- used for context in explanations
          - previous_approaches (list[str])
        The input dict is never mutated.

    Returns
    -------
    A dict containing exactly two keys:
        approach_used  : str  -- one of the four frozen ApproachUsed enum values
        resource_given : str  -- flat string describing the intervention resource

    Notes
    -----
    - Never repeats an approach already in previous_approaches unless all four
      have been exhausted.
    - Fully deterministic: same input always produces the same output.
    - Does not call any LLM or external service.
    """
    misconception       = student_state["misconception"]
    previous_approaches = list(student_state.get("previous_approaches", []))

    preferred_order = _get_preferred_order(misconception)
    approach        = _select_approach(preferred_order, previous_approaches)
    resource        = _build_resource(misconception, approach)

    return {
        "approach_used":  approach,
        "resource_given": resource,
    }


# ---------------------------------------------------------------------------
# Smoke tests -- run when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import copy
    import sys

    VALID_APPROACHES = set(APPROACHES)
    OUTPUT_FIELDS    = {"approach_used", "resource_given"}

    errors: list[str] = []

    def assert_ok(label: str, condition: bool, message: str = "") -> None:
        if condition:
            print("[OK]  " + label)
        else:
            msg = label + (": " + message if message else "")
            errors.append(msg)
            print("[FAIL]" + " " + msg)

    # ── shared base state ────────────────────────────────────────────────────
    base_state = {
        "student_id":          "s1",
        "topic":               "fraction_addition",
        "misconception":       "adds denominators directly",
        "status":              "diagnosed",
        "attempts":            0,
        "resource_given":      "",
        "approach_used":       "worked_example",
        "previous_approaches": [],
        "verification_result": "pending",
        "flagged_false_mastery": False,
    }

    print("=" * 60)
    print("CASE 1: Known misconception, empty previous_approaches")
    state1 = copy.deepcopy(base_state)
    snap1  = copy.deepcopy(state1)
    r1     = recommend_intervention(state1)

    assert_ok("C1 approach_used in enum",
              r1["approach_used"] in VALID_APPROACHES)
    assert_ok("C1 output has exactly required fields",
              set(r1.keys()) == OUTPUT_FIELDS)
    assert_ok("C1 resource_given is flat string",
              isinstance(r1["resource_given"], str) and len(r1["resource_given"]) > 0)
    assert_ok("C1 preferred first approach selected",
              r1["approach_used"] == "worked_example",
              "expected worked_example for 'adds denominators directly', got " + r1["approach_used"])
    assert_ok("C1 input not mutated",
              state1 == snap1)
    print("    approach_used  : " + r1["approach_used"])
    print("    resource_given : " + r1["resource_given"][:80] + "...")

    print()
    print("=" * 60)
    print("CASE 2: Same misconception after preferred approach already used")
    state2 = copy.deepcopy(base_state)
    state2["previous_approaches"] = ["worked_example"]
    r2     = recommend_intervention(state2)

    assert_ok("C2 approach_used in enum",
              r2["approach_used"] in VALID_APPROACHES)
    assert_ok("C2 does not repeat worked_example",
              r2["approach_used"] != "worked_example",
              "should skip worked_example; got " + r2["approach_used"])
    assert_ok("C2 resource_given is flat string",
              isinstance(r2["resource_given"], str) and len(r2["resource_given"]) > 0)
    print("    approach_used  : " + r2["approach_used"])

    print()
    print("=" * 60)
    print("CASE 3: Unknown misconception")
    state3 = copy.deepcopy(base_state)
    state3["misconception"]       = "confuses area with perimeter"
    state3["topic"]               = "geometry"
    state3["previous_approaches"] = []
    r3 = recommend_intervention(state3)

    assert_ok("C3 approach_used in enum",
              r3["approach_used"] in VALID_APPROACHES)
    assert_ok("C3 output has exactly required fields",
              set(r3.keys()) == OUTPUT_FIELDS)
    assert_ok("C3 resource_given is flat string",
              isinstance(r3["resource_given"], str) and len(r3["resource_given"]) > 0)
    print("    approach_used  : " + r3["approach_used"])
    print("    resource_given : " + r3["resource_given"][:80] + "...")

    print()
    print("=" * 60)
    print("CASE 4: All four approaches already used (exhaustion / restart)")
    state4 = copy.deepcopy(base_state)
    state4["previous_approaches"] = [
        "worked_example", "analogy", "visual_description", "direct_explanation"
    ]
    r4 = recommend_intervention(state4)

    assert_ok("C4 approach_used in enum",
              r4["approach_used"] in VALID_APPROACHES,
              "got " + r4["approach_used"])
    assert_ok("C4 returns something (does not crash)",
              bool(r4.get("approach_used")) and bool(r4.get("resource_given")))
    print("    approach_used  : " + r4["approach_used"] + " (restarted from top)")

    print()
    print("=" * 60)
    print("CASE 5: Determinism — two identical calls produce identical output")
    state5a = copy.deepcopy(base_state)
    state5b = copy.deepcopy(base_state)
    r5a = recommend_intervention(state5a)
    r5b = recommend_intervention(state5b)

    assert_ok("C5 deterministic (approach_used)",
              r5a["approach_used"] == r5b["approach_used"])
    assert_ok("C5 deterministic (resource_given)",
              r5a["resource_given"] == r5b["resource_given"])

    print()
    print("=" * 60)
    print("CASE 6: Decimal misconception — preferred approach is visual_description")
    state6 = copy.deepcopy(base_state)
    state6["misconception"]       = "shifts decimal point in wrong direction when multiplying by powers of ten"
    state6["topic"]               = "decimal_multiplication"
    state6["previous_approaches"] = []
    r6 = recommend_intervention(state6)

    assert_ok("C6 approach_used in enum",
              r6["approach_used"] in VALID_APPROACHES)
    assert_ok("C6 preferred first approach for decimal misconception",
              r6["approach_used"] == "visual_description",
              "expected visual_description, got " + r6["approach_used"])
    print("    approach_used  : " + r6["approach_used"])

    print()
    print("=" * 60)
    print("CASE 7: Mixed fraction misconception — preferred approach is analogy")
    state7 = copy.deepcopy(base_state)
    state7["misconception"]       = "ignores whole number part in mixed fractions"
    state7["topic"]               = "fraction_addition"
    state7["previous_approaches"] = []
    r7 = recommend_intervention(state7)

    assert_ok("C7 approach_used in enum",
              r7["approach_used"] in VALID_APPROACHES)
    assert_ok("C7 preferred first approach for mixed fraction misconception",
              r7["approach_used"] == "analogy",
              "expected analogy, got " + r7["approach_used"])
    print("    approach_used  : " + r7["approach_used"])

    print()
    print("=" * 60)
    print("CASE 8: Approach skipping — decimal misconception, visual_description already used")
    state8 = copy.deepcopy(base_state)
    state8["misconception"]       = "shifts decimal point in wrong direction when multiplying by powers of ten"
    state8["topic"]               = "decimal_multiplication"
    state8["previous_approaches"] = ["visual_description"]
    r8 = recommend_intervention(state8)

    assert_ok("C8 approach_used in enum",
              r8["approach_used"] in VALID_APPROACHES)
    assert_ok("C8 skips visual_description (already used)",
              r8["approach_used"] != "visual_description",
              "should skip visual_description; got " + r8["approach_used"])
    print("    approach_used  : " + r8["approach_used"])

    # ── Final report ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if errors:
        print("ASSERTIONS FAILED:")
        for e in errors:
            print("  FAIL  " + e)
        sys.exit(1)
    else:
        print("All smoke-test assertions PASSED")
        sys.exit(0)
