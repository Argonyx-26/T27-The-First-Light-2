"""
verification_agent.py -- Person B: Intervention & Verification
==============================================================
Determines whether a student's diagnosed misconception was actually
resolved after an intervention, using a three-stage transfer progression:

    near_transfer  ->  far_transfer  ->  novel_context

Classification rule (from README / spec):
    near_transfer FAILS                          -> unresolved
    near_transfer PASS, far_transfer FAILS        -> surface_mastery
    near_transfer PASS, far_transfer PASS,
        novel_context FAILS                       -> surface_mastery
    all three PASS                               -> true_mastery

IMPORTANT contract notes:
  - `reasoning` is ephemeral -- returned by this function but NEVER written
    to shared/live_state.json.
  - Verification probes are internal/ephemeral -- never written to shared state.
  - This agent is fully deterministic. No LLM, no random, no external calls.
  - The input student_state dict is never mutated.

Contract reference: contract/schema.json  (VerificationResult enum)
"""

from __future__ import annotations

from typing import Any, NamedTuple

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------

VALID_VERIFICATION_RESULTS: frozenset[str] = frozenset(
    ["true_mastery", "surface_mastery", "unresolved"]
)

# ---------------------------------------------------------------------------
# Internal data structures (ephemeral -- never written to shared state)
# ---------------------------------------------------------------------------


class Probe(NamedTuple):
    """A single verification probe (ephemeral, local only)."""
    stage:       str   # "near_transfer" | "far_transfer" | "novel_context"
    description: str   # human-readable probe prompt (for reasoning string)
    passed:      bool  # simulated student response


class ProbeSet(NamedTuple):
    """The three transfer probes for one verification session."""
    near_transfer: Probe
    far_transfer:  Probe
    novel_context: Probe


# ---------------------------------------------------------------------------
# Deterministic simulated-response engine
#
# The student's simulated response at each stage is derived from:
#   1. misconception keyword(s)
#   2. approach_used (what intervention was delivered)
#   3. attempts count (proxy for how many cycles the student has been through)
#   4. previous_approaches length (correlated with effort/exposure)
#
# Rules are calibrated so that the three mock outcome categories map to the
# known mock_students.json states:
#
#   true_mastery   : attempts >= 2 OR approach matched a high-efficacy path
#   surface_mastery: attempts == 1 AND approach is the very first (preferred)
#   unresolved     : approach is in a low-efficacy position AND attempts >= 2
#                    (i.e. they tried multiple approaches and still failed)
#
# This is an explicit MVP simulation -- no randomness is involved.
# ---------------------------------------------------------------------------

# Approach efficacy score per misconception keyword.
# Higher score -> more likely to produce mastery.
# Scores are ordinal; compare pairs, not absolute values.
_APPROACH_EFFICACY: dict[str, dict[str, int]] = {
    "adds denominator": {
        "worked_example":    3,
        "visual_description":2,
        "analogy":           2,
        "direct_explanation":1,
    },
    "decimal point": {
        "visual_description":3,
        "analogy":           2,
        "worked_example":    2,
        "direct_explanation":1,
    },
    "powers of ten": {
        "visual_description":3,
        "analogy":           2,
        "worked_example":    2,
        "direct_explanation":1,
    },
    "whole number": {
        "analogy":           3,
        "worked_example":    2,
        "direct_explanation":2,
        "visual_description":1,
    },
    "mixed fraction": {
        "analogy":           3,
        "worked_example":    2,
        "direct_explanation":2,
        "visual_description":1,
    },
    "equivalent fraction": {
        "visual_description":3,
        "analogy":           2,
        "worked_example":    2,
        "direct_explanation":1,
    },
    # Generic fallback used when no keyword matches
    "_fallback": {
        "direct_explanation":3,
        "worked_example":    2,
        "analogy":           2,
        "visual_description":1,
    },
}


def _efficacy_score(misconception: str, approach: str) -> int:
    """Return the efficacy score for (misconception, approach)."""
    mc = misconception.lower()
    for keyword, scores in _APPROACH_EFFICACY.items():
        if keyword == "_fallback":
            continue
        if keyword in mc:
            return scores.get(approach, 1)
    return _APPROACH_EFFICACY["_fallback"].get(approach, 1)


def _simulate_responses(
    misconception: str,
    approach_used: str,
    attempts: int,
    previous_approaches: list[str],
) -> tuple[bool, bool, bool]:
    """
    Return (near_pass, far_pass, novel_pass) deterministically.

    Design rationale
    ----------------
    near_transfer  : passes unless the approach was very low efficacy (score 1)
                     AND this is their first attempt.
    far_transfer   : passes when efficacy >= 2 OR attempts >= 2
                     (repeated exposure increases far-transfer success).
    novel_context  : passes only when efficacy == 3 AND attempts >= 2,
                     OR when attempts >= 3 (high persistence -> generalisation).

    This yields the three required demo outcomes:

    true_mastery   -> high-efficacy approach (score 3) with attempts >= 2
    surface_mastery-> approach score 2-3 on first attempt (near/far pass,
                     novel fails) OR approach score >= 2 on attempt 1
    unresolved     -> low-efficacy approach (score 1) on first attempt
                     OR multiple escalations (attempts >= 2, score 1)
    """
    score   = _efficacy_score(misconception, approach_used)
    n_prev  = len(previous_approaches)

    # near_transfer: fails only when score == 1 AND first attempt
    near_pass = not (score == 1 and attempts <= 1)

    # far_transfer: passes if efficacy is adequate OR student has more exposure
    far_pass = (score >= 2) or (attempts >= 2 and score >= 1)

    # novel_context: requires high efficacy AND sufficient attempts
    # OR enough repeated practice (attempts >= 3)
    novel_pass = (score == 3 and attempts >= 2) or (attempts >= 3)

    return near_pass, far_pass, novel_pass


# ---------------------------------------------------------------------------
# Probe generation (ephemeral descriptions -- never written to shared state)
# ---------------------------------------------------------------------------

# (misconception_keyword, stage) -> probe description
_PROBE_DESCRIPTIONS: dict[tuple[str, str], str] = {
    # adds denominators directly
    ("adds denominator", "near_transfer"): (
        "Near transfer: Calculate 1/4 + 1/4. "
        "(Same denominator -- tests whether the student applies the algorithm.)"
    ),
    ("adds denominator", "far_transfer"): (
        "Far transfer: Calculate 2/3 + 3/5. "
        "(Different denominator structure -- tests conceptual generalisation.)"
    ),
    ("adds denominator", "novel_context"): (
        "Novel context: 'A recipe uses 1/3 cup of oil and 2/5 cup of water. "
        "How much liquid is used in total?' "
        "(Word problem requiring the same underlying principle.)"
    ),
    # decimal point / powers of ten
    ("decimal point", "near_transfer"): (
        "Near transfer: What is 3.6 x 10? "
        "(Direct multiplication -- same surface form as the worked example.)"
    ),
    ("decimal point", "far_transfer"): (
        "Far transfer: A number is multiplied by 100 and the result is 450. "
        "What was the original number? "
        "(Inverse operation -- tests conceptual flexibility.)"
    ),
    ("decimal point", "novel_context"): (
        "Novel context: 'A ribbon is 0.75 m long. How long would 10 identical "
        "ribbons be when laid end to end?' "
        "(Measurement context requiring decimal multiplication.)"
    ),
    ("powers of ten", "near_transfer"): (
        "Near transfer: What is 0.08 x 10? "
        "(Direct multiplication by a power of ten.)"
    ),
    ("powers of ten", "far_transfer"): (
        "Far transfer: Write 5.4 x 10^2 as a decimal. "
        "(Exponential notation -- tests representational flexibility.)"
    ),
    ("powers of ten", "novel_context"): (
        "Novel context: 'A bacterium is 0.003 mm wide. A slide holds 1000 "
        "bacteria end to end. How wide is the row in mm?' "
        "(Applied science context.)"
    ),
    # whole number / mixed fractions
    ("whole number", "near_transfer"): (
        "Near transfer: Calculate 3 1/2 + 2 1/4. "
        "(Direct mixed-number addition -- tests the algorithm.)"
    ),
    ("whole number", "far_transfer"): (
        "Far transfer: Convert 5 3/8 to an improper fraction, then add 1/8. "
        "(Representation change -- tests conceptual flexibility.)"
    ),
    ("whole number", "novel_context"): (
        "Novel context: 'A shelf holds 2 1/3 rows of books and a second shelf "
        "holds 1 2/3 rows. How many rows in total?' "
        "(Applied context using mixed quantities.)"
    ),
    ("mixed fraction", "near_transfer"): (
        "Near transfer: Calculate 4 3/5 + 1 1/5. "
        "(Mixed number with same denominator -- tests the whole-number part.)"
    ),
    ("mixed fraction", "far_transfer"): (
        "Far transfer: Subtract 2 2/3 from 5. "
        "(Subtraction and whole-from-mixed -- tests representation flexibility.)"
    ),
    ("mixed fraction", "novel_context"): (
        "Novel context: 'You ran 2 3/4 km in the morning and 1 1/2 km in the "
        "evening. What is the total distance?' "
        "(Applied quantity context.)"
    ),
    # equivalent fractions
    ("equivalent fraction", "near_transfer"): (
        "Near transfer: Is 3/4 equivalent to 6/8? Show your reasoning. "
        "(Direct equivalence check.)"
    ),
    ("equivalent fraction", "far_transfer"): (
        "Far transfer: Simplify 18/24 to its lowest terms. "
        "(Reverse operation -- tests conceptual flexibility.)"
    ),
    ("equivalent fraction", "novel_context"): (
        "Novel context: 'A sale offers 2/5 off the price. A friend says that "
        "is the same as 4/10 off. Are they correct?' "
        "(Applied context with equivalence reasoning.)"
    ),
}

_FALLBACK_PROBES: dict[str, str] = {
    "near_transfer": (
        "Near transfer: Apply the core concept to a problem with the same "
        "surface structure as the worked intervention."
    ),
    "far_transfer": (
        "Far transfer: Apply the same underlying principle in a problem where "
        "the numbers, representation, or format have changed."
    ),
    "novel_context": (
        "Novel context: Solve a word problem set in a real-world scenario "
        "that requires the same conceptual understanding."
    ),
}


def _get_probe_description(misconception: str, stage: str) -> str:
    """Return a probe description for (misconception, stage)."""
    mc = misconception.lower()
    for keyword in _PROBE_DESCRIPTIONS:
        kw, s = keyword
        if kw in mc and s == stage:
            return _PROBE_DESCRIPTIONS[keyword]
    return _FALLBACK_PROBES.get(stage, "Probe: " + stage)


def _build_probe_set(
    misconception: str,
    approach_used: str,
    attempts: int,
    previous_approaches: list[str],
) -> ProbeSet:
    """
    Build the three transfer probes with simulated pass/fail responses.
    Entirely ephemeral -- never written to shared state.
    """
    near_pass, far_pass, novel_pass = _simulate_responses(
        misconception, approach_used, attempts, previous_approaches
    )
    return ProbeSet(
        near_transfer=Probe(
            stage="near_transfer",
            description=_get_probe_description(misconception, "near_transfer"),
            passed=near_pass,
        ),
        far_transfer=Probe(
            stage="far_transfer",
            description=_get_probe_description(misconception, "far_transfer"),
            passed=far_pass,
        ),
        novel_context=Probe(
            stage="novel_context",
            description=_get_probe_description(misconception, "novel_context"),
            passed=novel_pass,
        ),
    )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def _classify(probes: ProbeSet) -> tuple[str, str]:
    """
    Apply the classification rule from the spec and return
    (verification_result, reasoning).

    Rule (verbatim from README / spec):
        near_transfer FAILS                          -> unresolved
        near_transfer PASS + far_transfer FAILS      -> surface_mastery
        near_transfer PASS + far_transfer PASS
            + novel_context FAILS                    -> surface_mastery
        all three PASS                               -> true_mastery
    """
    near  = probes.near_transfer
    far   = probes.far_transfer
    novel = probes.novel_context

    stage_summary = (
        "Probe results -- "
        "near_transfer: " + ("PASS" if near.passed else "FAIL") + ", "
        "far_transfer: "  + ("PASS" if far.passed  else "FAIL") + ", "
        "novel_context: " + ("PASS" if novel.passed else "FAIL") + ". "
    )

    if not near.passed:
        return (
            "unresolved",
            stage_summary +
            "The student failed the near-transfer probe, indicating the "
            "misconception was not resolved by the intervention. "
            "Probe: " + near.description,
        )

    if not far.passed:
        return (
            "surface_mastery",
            stage_summary +
            "The student passed the near-transfer probe but failed far transfer, "
            "suggesting they recognised the familiar pattern without developing "
            "a generalisable conceptual understanding. "
            "Probe failed: " + far.description,
        )

    if not novel.passed:
        return (
            "surface_mastery",
            stage_summary +
            "The student passed near and far transfer but could not apply the "
            "concept in a novel real-world context, indicating surface rather "
            "than deep mastery. "
            "Probe failed: " + novel.description,
        )

    return (
        "true_mastery",
        stage_summary +
        "The student successfully generalised the concept across near-transfer, "
        "far-transfer, and novel-context probes, demonstrating genuine mastery.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_intervention(student_state: dict[str, Any]) -> dict[str, str]:
    """
    Verify whether a student's misconception was resolved after intervention.

    Parameters
    ----------
    student_state:
        A StudentState-compatible dict.  Fields read (never mutated):
          - misconception        (str)
          - approach_used        (str)
          - attempts             (int)
          - previous_approaches  (list[str])

    Returns
    -------
    A dict containing EXACTLY two keys:
        verification_result : str  -- one of true_mastery | surface_mastery | unresolved
        reasoning           : str  -- ephemeral explanation (NOT written to shared state)

    Notes
    -----
    - Verification probes are generated and evaluated internally.
      They are never written to shared/live_state.json.
    - reasoning is ephemeral and must NOT be stored in StudentState.
    - Fully deterministic: same input -> same output.
    - Does not call any LLM or external service.
    """
    misconception       = student_state["misconception"]
    approach_used       = student_state.get("approach_used", "worked_example")
    attempts            = int(student_state.get("attempts", 1))
    previous_approaches = list(student_state.get("previous_approaches", []))

    probes  = _build_probe_set(misconception, approach_used, attempts, previous_approaches)
    result, reasoning = _classify(probes)

    return {
        "verification_result": result,
        "reasoning":           reasoning,
    }


# ---------------------------------------------------------------------------
# Smoke tests -- run when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import copy
    import sys

    VALID_VR     = {"true_mastery", "surface_mastery", "unresolved"}
    OUTPUT_FIELDS = {"verification_result", "reasoning"}

    errors: list[str] = []

    def ok(label: str, condition: bool, note: str = "") -> None:
        if condition:
            print("[OK]  " + label)
        else:
            msg = label + (": " + note if note else "")
            errors.append(msg)
            print("[FAIL] " + msg)

    def make_state(**overrides) -> dict:
        base = {
            "student_id":           "s_test",
            "topic":                "fraction_addition",
            "misconception":        "adds denominators directly",
            "status":               "intervened",
            "attempts":             2,
            "resource_given":       "Worked example of fraction addition.",
            "approach_used":        "worked_example",
            "previous_approaches":  ["worked_example"],
            "verification_result":  "pending",
            "flagged_false_mastery": False,
        }
        base.update(overrides)
        return base

    # ── CASE 1: true_mastery ──────────────────────────────────────────────────
    print("=" * 60)
    print("CASE 1: true_mastery")
    print("  Setup: adds denominators directly, worked_example, attempts=2")
    s1 = make_state(
        misconception="adds denominators directly",
        approach_used="worked_example",
        attempts=2,
        previous_approaches=["worked_example"],
    )
    snap1 = copy.deepcopy(s1)
    r1 = verify_intervention(s1)

    ok("C1 output fields exact",   set(r1.keys()) == OUTPUT_FIELDS)
    ok("C1 vr in valid enum",      r1["verification_result"] in VALID_VR)
    ok("C1 true_mastery",          r1["verification_result"] == "true_mastery",
       "got " + r1["verification_result"])
    ok("C1 reasoning is str",      isinstance(r1["reasoning"], str) and len(r1["reasoning"]) > 0)
    ok("C1 input not mutated",     s1 == snap1)
    ok("C1 no probe key in input", "verification_probes" not in s1)
    print("  result  : " + r1["verification_result"])
    print("  reasoning: " + r1["reasoning"][:100] + "...")

    # ── CASE 2: surface_mastery ────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 2: surface_mastery")
    print("  Setup: adds denominators directly, worked_example, attempts=1")
    s2 = make_state(
        misconception="adds denominators directly",
        approach_used="worked_example",
        attempts=1,
        previous_approaches=["worked_example"],
    )
    snap2 = copy.deepcopy(s2)
    r2 = verify_intervention(s2)

    ok("C2 output fields exact",   set(r2.keys()) == OUTPUT_FIELDS)
    ok("C2 vr in valid enum",      r2["verification_result"] in VALID_VR)
    ok("C2 surface_mastery",       r2["verification_result"] == "surface_mastery",
       "got " + r2["verification_result"])
    ok("C2 reasoning is str",      isinstance(r2["reasoning"], str) and len(r2["reasoning"]) > 0)
    ok("C2 input not mutated",     s2 == snap2)
    print("  result  : " + r2["verification_result"])
    print("  reasoning: " + r2["reasoning"][:100] + "...")

    # ── CASE 3: unresolved ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 3: unresolved")
    print("  Setup: adds denominators directly, direct_explanation, attempts=1")
    s3 = make_state(
        misconception="adds denominators directly",
        approach_used="direct_explanation",   # low-efficacy (score=1) for this mc
        attempts=1,
        previous_approaches=["direct_explanation"],
    )
    snap3 = copy.deepcopy(s3)
    r3 = verify_intervention(s3)

    ok("C3 output fields exact",   set(r3.keys()) == OUTPUT_FIELDS)
    ok("C3 vr in valid enum",      r3["verification_result"] in VALID_VR)
    ok("C3 unresolved",            r3["verification_result"] == "unresolved",
       "got " + r3["verification_result"])
    ok("C3 reasoning is str",      isinstance(r3["reasoning"], str) and len(r3["reasoning"]) > 0)
    ok("C3 input not mutated",     s3 == snap3)
    print("  result  : " + r3["verification_result"])
    print("  reasoning: " + r3["reasoning"][:100] + "...")

    # ── CASE 4: all three probe stages evaluated ──────────────────────────────
    print()
    print("=" * 60)
    print("CASE 4: all three stages evaluated (verify ProbeSet is built)")
    s4 = make_state(attempts=2, approach_used="worked_example")
    probes4 = _build_probe_set(
        s4["misconception"], s4["approach_used"],
        s4["attempts"], s4["previous_approaches"]
    )
    ok("C4 near_transfer stage label",  probes4.near_transfer.stage == "near_transfer")
    ok("C4 far_transfer stage label",   probes4.far_transfer.stage == "far_transfer")
    ok("C4 novel_context stage label",  probes4.novel_context.stage == "novel_context")
    ok("C4 each probe has description", all(
        len(p.description) > 0 for p in [
            probes4.near_transfer, probes4.far_transfer, probes4.novel_context
        ]
    ))
    ok("C4 each probe has bool passed", all(
        isinstance(p.passed, bool) for p in [
            probes4.near_transfer, probes4.far_transfer, probes4.novel_context
        ]
    ))
    print("  near_transfer.passed : " + str(probes4.near_transfer.passed))
    print("  far_transfer.passed  : " + str(probes4.far_transfer.passed))
    print("  novel_context.passed : " + str(probes4.novel_context.passed))

    # ── CASE 5: unknown misconception does not crash ──────────────────────────
    print()
    print("=" * 60)
    print("CASE 5: unknown misconception does not crash")
    s5 = make_state(
        misconception="confuses velocity with acceleration",
        topic="physics",
        approach_used="analogy",
        attempts=2,
        previous_approaches=["analogy"],
    )
    try:
        r5 = verify_intervention(s5)
        ok("C5 no crash",           True)
        ok("C5 output fields exact", set(r5.keys()) == OUTPUT_FIELDS)
        ok("C5 vr in valid enum",    r5["verification_result"] in VALID_VR)
        print("  result: " + r5["verification_result"])
    except Exception as exc:
        ok("C5 no crash", False, str(exc))

    # ── CASE 6: determinism ───────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 6: determinism -- two identical calls")
    s6a = make_state(attempts=1, approach_used="worked_example")
    s6b = make_state(attempts=1, approach_used="worked_example")
    r6a = verify_intervention(s6a)
    r6b = verify_intervention(s6b)

    ok("C6 vr identical",       r6a["verification_result"] == r6b["verification_result"])
    ok("C6 reasoning identical", r6a["reasoning"] == r6b["reasoning"])

    # ── CASE 7: input not mutated (extra check with field enumeration) ────────
    print()
    print("=" * 60)
    print("CASE 7: input not mutated (extra fields check)")
    s7 = make_state(attempts=2, approach_used="visual_description")
    original_keys = set(s7.keys())
    original_vals = copy.deepcopy(s7)
    _ = verify_intervention(s7)
    ok("C7 no new keys added to input",    set(s7.keys()) == original_keys)
    ok("C7 values unchanged",              s7 == original_vals)
    ok("C7 verification_probes not in s7", "verification_probes" not in s7)

    # ── CASE 8: verification_result field only (no extra fields) ─────────────
    print()
    print("=" * 60)
    print("CASE 8: output has EXACTLY the two required fields")
    s8 = make_state(attempts=2, approach_used="analogy",
                    misconception="shifts decimal point in wrong direction when multiplying by powers of ten",
                    topic="decimal_multiplication")
    r8 = verify_intervention(s8)
    ok("C8 exact output fields",  set(r8.keys()) == OUTPUT_FIELDS,
       "got " + str(set(r8.keys())))
    ok("C8 vr in valid enum",     r8["verification_result"] in VALID_VR)
    print("  result: " + r8["verification_result"])

    # ── CASE 9: decimal misconception -- true_mastery with visual+attempts=2 ───
    print()
    print("=" * 60)
    print("CASE 9: decimal misconception, visual_description, attempts=2 -> true_mastery")
    s9 = make_state(
        misconception="shifts decimal point in wrong direction when multiplying by powers of ten",
        topic="decimal_multiplication",
        approach_used="visual_description",
        attempts=2,
        previous_approaches=["visual_description"],
    )
    r9 = verify_intervention(s9)
    ok("C9 vr in valid enum",  r9["verification_result"] in VALID_VR)
    ok("C9 true_mastery",      r9["verification_result"] == "true_mastery",
       "got " + r9["verification_result"])
    print("  result: " + r9["verification_result"])

    # ── CASE 10: mixed fraction misconception -- unresolved ────────────────────
    print()
    print("=" * 60)
    print("CASE 10: mixed fraction, visual_description (low-efficacy), attempts=1 -> unresolved")
    s10 = make_state(
        misconception="ignores whole number part in mixed fractions",
        topic="fraction_addition",
        approach_used="visual_description",   # score=1 for this mc
        attempts=1,
        previous_approaches=["visual_description"],
    )
    r10 = verify_intervention(s10)
    ok("C10 vr in valid enum", r10["verification_result"] in VALID_VR)
    ok("C10 unresolved",       r10["verification_result"] == "unresolved",
       "got " + r10["verification_result"])
    print("  result: " + r10["verification_result"])

    # ── Final report ──────────────────────────────────────────────────────────
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
