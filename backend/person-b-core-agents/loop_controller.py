"""
loop_controller.py -- Personalized Practice: Intervention & Verification
============================================================
Orchestrates the closed-loop teaching lifecycle by connecting
recommender_agent and verification_agent.

One call to advance() performs EXACTLY ONE lifecycle transition:

    diagnosed   -> intervened   (calls recommender)
    intervened  -> verifying    (no agent call; gate state)
    verifying   -> verified     (calls verification_agent; true/surface mastery)
    verifying   -> escalated    (calls verification_agent; unresolved)
    escalated   -> intervened   (calls recommender; new approach, increments attempts)

The controller never performs multiple transitions in one call.
The caller is responsible for calling advance() repeatedly to drive the loop.

Persistence:
    After every successful advance(), the updated state is written to
    shared/live_state.json (one JSON array of all StudentState objects).
    Only the loop_controller writes this file.
    Classroom Insights reads it; Learning Diagnosis supplies the initial diagnosed state.

Contract reference: contract/schema.json
    - StudentState: exactly 10 fields, no extras allowed.
    - reasoning from verify_intervention() is EPHEMERAL -- never stored.
    - verification probes are EPHEMERAL -- never stored.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Import sibling agents.
# When executed directly, adjust sys.path so the import resolves regardless
# of the working directory.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from recommender_agent  import recommend_intervention
from verification_agent import verify_intervention
from db_client import upsert_student_state

# ---------------------------------------------------------------------------
# Frozen enums (mirrors contract/schema.json)
# ---------------------------------------------------------------------------

VALID_STATUSES: frozenset[str] = frozenset(
    ["diagnosed", "intervened", "verifying", "verified", "escalated"]
)

VALID_APPROACHES: frozenset[str] = frozenset(
    ["worked_example", "analogy", "visual_description", "direct_explanation"]
)

VALID_VERIFICATION_RESULTS: frozenset[str] = frozenset(
    ["true_mastery", "surface_mastery", "unresolved", "pending"]
)

# Exactly the 10 contract fields -- used for output validation.
CONTRACT_FIELDS: tuple[str, ...] = (
    "student_id",
    "topic",
    "misconception",
    "status",
    "attempts",
    "resource_given",
    "approach_used",
    "previous_approaches",
    "verification_result",
    "flagged_false_mastery",
)

# Default path to the shared live-state file.
# Tests override this via the live_state_path parameter.
DEFAULT_LIVE_STATE_PATH = os.path.join(
    os.path.dirname(_HERE), "shared", "live_state.json"
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_input(state: dict[str, Any]) -> None:
    """
    Raise ValueError if the input student state is structurally invalid.
    Does NOT require all 10 fields to be present (callers may supply a
    minimal diagnosed state); validates only what is present.
    """
    if "student_id" not in state or not state["student_id"]:
        raise ValueError("student_state must contain a non-empty 'student_id'.")

    if "status" in state and state["status"] not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{state['status']}'. "
            f"Allowed: {sorted(VALID_STATUSES)}"
        )

    if "verification_result" in state and state["verification_result"] not in VALID_VERIFICATION_RESULTS:
        raise ValueError(
            f"Invalid verification_result '{state['verification_result']}'. "
            f"Allowed: {sorted(VALID_VERIFICATION_RESULTS)}"
        )

    if "approach_used" in state and state.get("approach_used") and \
            state["approach_used"] not in VALID_APPROACHES:
        raise ValueError(
            f"Invalid approach_used '{state['approach_used']}'. "
            f"Allowed: {sorted(VALID_APPROACHES)}"
        )

    prev = state.get("previous_approaches", [])
    if not isinstance(prev, list):
        raise ValueError("'previous_approaches' must be a list.")
    for ap in prev:
        if ap not in VALID_APPROACHES:
            raise ValueError(
                f"Invalid value '{ap}' in previous_approaches. "
                f"Allowed: {sorted(VALID_APPROACHES)}"
            )


def _enforce_contract(state: dict[str, Any]) -> dict[str, Any]:
    """
    Strip any extra fields and raise if any of the 10 required contract
    fields are absent.  Returns a clean dict with exactly 10 fields.
    """
    missing = [f for f in CONTRACT_FIELDS if f not in state]
    if missing:
        raise ValueError(
            f"Output state is missing required contract fields: {missing}"
        )
    return {f: state[f] for f in CONTRACT_FIELDS}


# ---------------------------------------------------------------------------
# Live-state persistence (shared/live_state.json)
# ---------------------------------------------------------------------------

def _load_live_state(path: str) -> list[dict[str, Any]]:
    """
    Load shared/live_state.json.
    Returns an empty list if the file does not exist.
    Raises ValueError if the file exists but contains invalid JSON.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(
                f"live_state.json at '{path}' must be a JSON array at the top level."
            )
        return data
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"shared/live_state.json is malformed and cannot be parsed. "
            f"Fix or delete the file before continuing. "
            f"JSON error: {exc}"
        ) from exc


def _save_live_state(path: str, updated_student: dict[str, Any]) -> None:
    """
    Upsert the updated student into Supabase with fallback to the live-state file.
    - If student_id already exists: replace it in-place.
    - Otherwise: append.
    """
    try:
        upsert_student_state(updated_student)
    except Exception as e:
        print(f"[Loop Controller] Supabase upsert failed: {e}. Falling back to live_state.json.")

    records = _load_live_state(path)
    sid = updated_student["student_id"]

    # Replace existing or append
    found = False
    for i, rec in enumerate(records):
        if rec.get("student_id") == sid:
            records[i] = updated_student
            found = True
            break
    if not found:
        records.append(updated_student)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# State-transition helpers
# ---------------------------------------------------------------------------

def _copy_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with a fresh copy of previous_approaches."""
    out = dict(state)
    out["previous_approaches"] = list(state.get("previous_approaches", []))
    return out


def _transition_diagnosed(state: dict[str, Any]) -> dict[str, Any]:
    """
    diagnosed -> intervened

    Calls the recommender to select an approach and generate resource_given.
    Appends the selected approach to previous_approaches exactly once.
    Does NOT increment attempts -- the initial diagnosed state already
    represents attempt #1 conceptually; the counter starts at whatever
    the caller supplied (typically 1).
    """
    rec = recommend_intervention(state)
    approach  = rec["approach_used"]
    resource  = rec["resource_given"]

    out = _copy_state(state)
    out["approach_used"]  = approach
    out["resource_given"] = resource
    out["status"]         = "intervened"

    # Append only if not already the last entry (idempotency guard)
    if not out["previous_approaches"] or out["previous_approaches"][-1] != approach:
        out["previous_approaches"].append(approach)

    return out


def _transition_intervened(state: dict[str, Any]) -> dict[str, Any]:
    """
    intervened -> verifying

    Pure state gate -- no agent call.
    The verifying state signals that probes are being administered.
    """
    out = _copy_state(state)
    out["status"]              = "verifying"
    out["verification_result"] = "pending"
    return out


def _transition_verifying(state: dict[str, Any]) -> dict[str, Any]:
    """
    verifying -> verified | escalated

    Calls verify_intervention() and applies the classification rule:
        true_mastery   -> verified,   flagged_false_mastery=False
        surface_mastery-> verified,   flagged_false_mastery=True
        unresolved     -> escalated,  flagged_false_mastery=False

    reasoning from verify_intervention() is ephemeral and is NOT stored
    in the returned state (contract forbids it).
    """
    result_dict = verify_intervention(state)
    vr = result_dict["verification_result"]
    # reasoning is intentionally discarded here -- ephemeral per spec.

    out = _copy_state(state)
    out["verification_result"] = vr

    if vr == "true_mastery":
        out["status"]               = "verified"
        out["flagged_false_mastery"] = False

    elif vr == "surface_mastery":
        out["status"]               = "verified"
        out["flagged_false_mastery"] = True

    elif vr == "unresolved":
        out["status"]               = "escalated"
        out["flagged_false_mastery"] = False

    else:
        # Should never happen given our deterministic verification_agent,
        # but guard defensively.
        raise ValueError(
            f"verify_intervention returned unexpected result: '{vr}'. "
            f"Expected one of: true_mastery, surface_mastery, unresolved."
        )

    return out


def _transition_escalated(state: dict[str, Any]) -> dict[str, Any]:
    """
    escalated -> intervened

    Calls the recommender again.  The recommender inspects previous_approaches
    and selects a different approach automatically.

    Increments attempts because this is a NEW intervention attempt.
    Appends the new approach to previous_approaches exactly once.
    """
    out = _copy_state(state)
    out["attempts"] = int(state.get("attempts", 1)) + 1

    rec      = recommend_intervention(out)
    approach = rec["approach_used"]
    resource = rec["resource_given"]

    out["approach_used"]  = approach
    out["resource_given"] = resource
    out["status"]         = "intervened"
    # Reset to pending before the next verification round
    out["verification_result"] = "pending"

    # Append only if not already the last entry
    if not out["previous_approaches"] or out["previous_approaches"][-1] != approach:
        out["previous_approaches"].append(approach)

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def advance(
    student_state: dict[str, Any],
    *,
    live_state_path: str | None = None,
) -> dict[str, Any]:
    """
    Perform exactly ONE lifecycle transition for the given student.

    Parameters
    ----------
    student_state:
        A StudentState-compatible dict.  The input is never mutated.
    live_state_path:
        Override the path to shared/live_state.json.  Used by tests to
        write to a temporary location instead of the real shared file.
        Defaults to shared/live_state.json relative to this file's parent.

    Returns
    -------
    A new dict containing EXACTLY the 10 contract fields with the
    updated student state after one lifecycle step.

    Raises
    ------
    ValueError
        - If student_state fails validation.
        - If the current status has no defined transition.
        - If shared/live_state.json exists but is malformed JSON.
        - If the resulting state is missing required contract fields.
    """
    path = live_state_path or DEFAULT_LIVE_STATE_PATH

    _validate_input(student_state)

    # Ensure the input has all required fields with safe defaults
    # (supports callers who only supply a minimal diagnosed state).
    canonical: dict[str, Any] = {
        "student_id":           student_state.get("student_id", ""),
        "topic":                student_state.get("topic", ""),
        "misconception":        student_state.get("misconception", ""),
        "status":               student_state.get("status", "diagnosed"),
        "attempts":             int(student_state.get("attempts", 1)),
        "resource_given":       student_state.get("resource_given", ""),
        "approach_used":        student_state.get("approach_used", "worked_example"),
        "previous_approaches":  list(student_state.get("previous_approaches", [])),
        "verification_result":  student_state.get("verification_result", "pending"),
        "flagged_false_mastery": bool(student_state.get("flagged_false_mastery", False)),
    }

    status = canonical["status"]

    # Route to the correct transition handler
    if status == "diagnosed":
        updated = _transition_diagnosed(canonical)
    elif status == "intervened":
        updated = _transition_intervened(canonical)
    elif status == "verifying":
        updated = _transition_verifying(canonical)
    elif status == "escalated":
        updated = _transition_escalated(canonical)
    elif status == "verified":
        # Terminal state -- no further transition.
        # Return as-is so callers can call advance() safely on a verified student.
        updated = _copy_state(canonical)
    else:
        raise ValueError(
            f"Unknown status '{status}'. No lifecycle transition defined. "
            f"Allowed: {sorted(VALID_STATUSES)}"
        )

    # Enforce contract: exactly 10 fields, no extras
    result = _enforce_contract(updated)

    # Persist to shared/live_state.json
    _save_live_state(path, result)

    return result


# ---------------------------------------------------------------------------
# Smoke tests -- run when this file is executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import copy
    import tempfile

    errors: list[str] = []

    def ok(label: str, condition: bool, note: str = "") -> None:
        if condition:
            print("[OK]  " + label)
        else:
            msg = label + (": " + note if note else "")
            errors.append(msg)
            print("[FAIL] " + msg)

    def make_diagnosed(**overrides) -> dict:
        base = {
            "student_id":           "s_test",
            "topic":                "fraction_addition",
            "misconception":        "adds denominators directly",
            "status":               "diagnosed",
            "attempts":             1,
            "resource_given":       "",
            "approach_used":        "worked_example",
            "previous_approaches":  [],
            "verification_result":  "pending",
            "flagged_false_mastery": False,
        }
        base.update(overrides)
        return base

    # Each test gets its own temp file for live_state.json
    def tmp_path() -> str:
        fd, path = tempfile.mkstemp(suffix=".json", prefix="live_state_test_")
        os.close(fd)
        os.unlink(path)   # delete so it starts non-existent
        return path

    CONTRACT_SET = set(CONTRACT_FIELDS)

    # ── CASE 1: diagnosed -> intervened ──────────────────────────────────────
    print("=" * 60)
    print("CASE 1: diagnosed -> intervened")
    p1 = tmp_path()
    s1_in   = make_diagnosed()
    snap1   = copy.deepcopy(s1_in)
    s1_out  = advance(s1_in, live_state_path=p1)

    ok("C1 input not mutated",             s1_in == snap1)
    ok("C1 status = intervened",           s1_out["status"] == "intervened",
       "got " + s1_out["status"])
    ok("C1 approach_used in enum",         s1_out["approach_used"] in VALID_APPROACHES)
    ok("C1 resource_given non-empty",      isinstance(s1_out["resource_given"], str) and
       len(s1_out["resource_given"]) > 0)
    ok("C1 previous_approaches updated",   len(s1_out["previous_approaches"]) == 1 and
       s1_out["previous_approaches"][0] == s1_out["approach_used"])
    ok("C1 exactly 10 contract fields",    set(s1_out.keys()) == CONTRACT_SET,
       "extra/missing: " + str(set(s1_out.keys()) ^ CONTRACT_SET))
    ok("C1 attempts unchanged (still 1)",  s1_out["attempts"] == 1)
    print("  approach_used: " + s1_out["approach_used"])

    # ── CASE 2: intervened -> verifying ──────────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 2: intervened -> verifying")
    p2 = tmp_path()
    s2_in  = dict(s1_out)
    s2_out = advance(s2_in, live_state_path=p2)

    ok("C2 status = verifying",            s2_out["status"] == "verifying",
       "got " + s2_out["status"])
    ok("C2 exactly 10 contract fields",    set(s2_out.keys()) == CONTRACT_SET)
    ok("C2 verification_result = pending", s2_out["verification_result"] == "pending")

    # ── CASE 3: verifying -> true_mastery / verified ──────────────────────────
    print()
    print("=" * 60)
    print("CASE 3: verifying -> true_mastery (attempts=2, worked_example)")
    p3 = tmp_path()
    s3_in = make_diagnosed(
        status="verifying",
        approach_used="worked_example",
        attempts=2,
        previous_approaches=["worked_example"],
        verification_result="pending",
    )
    s3_out = advance(s3_in, live_state_path=p3)

    ok("C3 status = verified",             s3_out["status"] == "verified",
       "got " + s3_out["status"])
    ok("C3 verification_result = true_mastery",
       s3_out["verification_result"] == "true_mastery",
       "got " + s3_out["verification_result"])
    ok("C3 flagged_false_mastery = False",  s3_out["flagged_false_mastery"] is False)
    ok("C3 exactly 10 contract fields",    set(s3_out.keys()) == CONTRACT_SET)

    # ── CASE 4: verifying -> surface_mastery / verified ───────────────────────
    print()
    print("=" * 60)
    print("CASE 4: verifying -> surface_mastery (attempts=1, worked_example)")
    p4 = tmp_path()
    s4_in = make_diagnosed(
        status="verifying",
        approach_used="worked_example",
        attempts=1,
        previous_approaches=["worked_example"],
        verification_result="pending",
    )
    s4_out = advance(s4_in, live_state_path=p4)

    ok("C4 status = verified",             s4_out["status"] == "verified",
       "got " + s4_out["status"])
    ok("C4 verification_result = surface_mastery",
       s4_out["verification_result"] == "surface_mastery",
       "got " + s4_out["verification_result"])
    ok("C4 flagged_false_mastery = True",   s4_out["flagged_false_mastery"] is True)
    ok("C4 exactly 10 contract fields",    set(s4_out.keys()) == CONTRACT_SET)

    # ── CASE 5: verifying -> unresolved / escalated ───────────────────────────
    print()
    print("=" * 60)
    print("CASE 5: verifying -> unresolved (attempts=1, direct_explanation/low-efficacy)")
    p5 = tmp_path()
    s5_in = make_diagnosed(
        status="verifying",
        approach_used="direct_explanation",  # low efficacy for this mc
        attempts=1,
        previous_approaches=["direct_explanation"],
        verification_result="pending",
    )
    s5_out = advance(s5_in, live_state_path=p5)

    ok("C5 status = escalated",            s5_out["status"] == "escalated",
       "got " + s5_out["status"])
    ok("C5 verification_result = unresolved",
       s5_out["verification_result"] == "unresolved",
       "got " + s5_out["verification_result"])
    ok("C5 flagged_false_mastery = False",  s5_out["flagged_false_mastery"] is False)
    ok("C5 exactly 10 contract fields",    set(s5_out.keys()) == CONTRACT_SET)

    # ── CASE 6: escalated -> intervened (new approach, incremented attempts) ──
    print()
    print("=" * 60)
    print("CASE 6: escalated -> intervened")
    p6 = tmp_path()
    prev_approach = s5_out["approach_used"]
    prev_attempts = s5_out["attempts"]
    s6_out = advance(s5_out, live_state_path=p6)

    ok("C6 status = intervened",           s6_out["status"] == "intervened",
       "got " + s6_out["status"])
    ok("C6 attempts incremented",          s6_out["attempts"] == prev_attempts + 1,
       f"expected {prev_attempts+1}, got {s6_out['attempts']}")
    ok("C6 approach_used in enum",         s6_out["approach_used"] in VALID_APPROACHES)
    ok("C6 new approach != old approach",  s6_out["approach_used"] != prev_approach,
       f"new={s6_out['approach_used']} old={prev_approach}")
    ok("C6 previous_approaches extended",  prev_approach in s6_out["previous_approaches"] and
       s6_out["approach_used"] in s6_out["previous_approaches"])
    ok("C6 exactly 10 contract fields",    set(s6_out.keys()) == CONTRACT_SET)
    print("  old approach: " + prev_approach + "  new: " + s6_out["approach_used"])

    # ── CASE 7: live_state.json created when it does not exist ────────────────
    print()
    print("=" * 60)
    print("CASE 7: live_state.json created when missing")
    p7 = tmp_path()   # deleted above, does not exist
    ok("C7 file does not exist before",    not os.path.exists(p7))
    advance(make_diagnosed(student_id="s_new"), live_state_path=p7)
    ok("C7 file created after advance",    os.path.exists(p7))
    with open(p7, encoding="utf-8") as f:
        records7 = json.load(f)
    ok("C7 file contains valid JSON array", isinstance(records7, list))
    ok("C7 student written to file",       any(r["student_id"] == "s_new" for r in records7))
    os.unlink(p7)

    # ── CASE 8: existing student replaced without duplicate ───────────────────
    print()
    print("=" * 60)
    print("CASE 8: existing student_id replaced, no duplicate")
    p8 = tmp_path()
    # First write: diagnosed -> intervened
    s8a = advance(make_diagnosed(student_id="s_dup"), live_state_path=p8)
    # Second write: intervened -> verifying
    s8b = advance(s8a, live_state_path=p8)
    with open(p8, encoding="utf-8") as f:
        records8 = json.load(f)
    ids8 = [r["student_id"] for r in records8]
    ok("C8 no duplicate student_id",       ids8.count("s_dup") == 1,
       "count=" + str(ids8.count("s_dup")))
    ok("C8 latest state written",          records8[0]["status"] == "verifying")
    os.unlink(p8)

    # ── CASE 9: multiple students preserved ───────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 9: multiple students preserved in live_state.json")
    p9 = tmp_path()
    advance(make_diagnosed(student_id="s_alpha"), live_state_path=p9)
    advance(make_diagnosed(student_id="s_beta"),  live_state_path=p9)
    advance(make_diagnosed(student_id="s_gamma"), live_state_path=p9)
    with open(p9, encoding="utf-8") as f:
        records9 = json.load(f)
    ids9 = {r["student_id"] for r in records9}
    ok("C9 all three students present",    ids9 == {"s_alpha", "s_beta", "s_gamma"},
       "found: " + str(ids9))
    ok("C9 three records total",           len(records9) == 3)
    os.unlink(p9)

    # ── CASE 10: malformed live_state.json raises ValueError ─────────────────
    print()
    print("=" * 60)
    print("CASE 10: malformed live_state.json raises ValueError")
    p10_fd, p10 = tempfile.mkstemp(suffix=".json", prefix="live_state_bad_")
    os.close(p10_fd)
    with open(p10, "w", encoding="utf-8") as f:
        f.write("{this is: not valid json{{")
    try:
        advance(make_diagnosed(student_id="s_bad"), live_state_path=p10)
        ok("C10 raises ValueError", False, "no exception raised")
    except ValueError as exc:
        ok("C10 raises ValueError", True)
        ok("C10 error message mentions malformed", "malformed" in str(exc).lower() or
           "cannot be parsed" in str(exc).lower(), str(exc)[:60])
    finally:
        os.unlink(p10)

    # ── CASE 11: input state is not mutated ───────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 11: input state not mutated")
    p11 = tmp_path()
    s11_in  = make_diagnosed()
    snap11  = copy.deepcopy(s11_in)
    _       = advance(s11_in, live_state_path=p11)
    ok("C11 input not mutated",            s11_in == snap11)
    ok("C11 no extra keys in input",       set(s11_in.keys()) == set(snap11.keys()))
    os.unlink(p11)

    # ── CASE 12: output has exactly 10 contract fields ────────────────────────
    print()
    print("=" * 60)
    print("CASE 12: output has exactly the 10 contract fields")
    p12 = tmp_path()
    s12_out = advance(make_diagnosed(), live_state_path=p12)
    ok("C12 exactly 10 fields",            set(s12_out.keys()) == CONTRACT_SET,
       str(set(s12_out.keys()) ^ CONTRACT_SET))
    ok("C12 no 'reasoning' in output",     "reasoning" not in s12_out)
    ok("C12 no 'verification_probes'",     "verification_probes" not in s12_out)
    os.unlink(p12)

    # ── CASE 13: single advance = single transition ───────────────────────────
    print()
    print("=" * 60)
    print("CASE 13: one advance() = exactly one lifecycle transition")
    p13 = tmp_path()
    s13_diagnosed  = make_diagnosed()
    s13_intervened = advance(s13_diagnosed, live_state_path=p13)
    ok("C13 diagnosed->intervened (not verifying/verified)",
       s13_intervened["status"] == "intervened",
       "got " + s13_intervened["status"])
    s13_verifying  = advance(s13_intervened, live_state_path=p13)
    ok("C13 intervened->verifying (not verified)",
       s13_verifying["status"] == "verifying",
       "got " + s13_verifying["status"])
    os.unlink(p13)

    # ── CASE 14: determinism ──────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("CASE 14: determinism -- two identical calls produce identical output")
    p14a, p14b = tmp_path(), tmp_path()
    s14_in = make_diagnosed(
        status="verifying",
        approach_used="worked_example",
        attempts=2,
        previous_approaches=["worked_example"],
    )
    r14a = advance(s14_in, live_state_path=p14a)
    r14b = advance(s14_in, live_state_path=p14b)
    ok("C14 status identical",             r14a["status"] == r14b["status"])
    ok("C14 verification_result identical", r14a["verification_result"] == r14b["verification_result"])
    ok("C14 flagged_false_mastery identical", r14a["flagged_false_mastery"] == r14b["flagged_false_mastery"])
    os.unlink(p14a); os.unlink(p14b)

    # ── CASE 15: no invalid enum values in output ─────────────────────────────
    print()
    print("=" * 60)
    print("CASE 15: no invalid enum values in output")
    p15 = tmp_path()
    s15_out = advance(make_diagnosed(), live_state_path=p15)
    ok("C15 status in valid set",          s15_out["status"] in VALID_STATUSES)
    ok("C15 approach_used in valid set",   s15_out["approach_used"] in VALID_APPROACHES)
    ok("C15 verification_result in valid", s15_out["verification_result"] in VALID_VERIFICATION_RESULTS)
    ok("C15 flagged_false_mastery bool",   isinstance(s15_out["flagged_false_mastery"], bool))
    os.unlink(p15)

    # ── CASE 16: exhausted approaches do not crash ────────────────────────────
    print()
    print("=" * 60)
    print("CASE 16: all four approaches exhausted -- no crash")
    p16 = tmp_path()
    s16_in = make_diagnosed(
        status="escalated",
        verification_result="unresolved",
        previous_approaches=[
            "worked_example", "analogy", "visual_description", "direct_explanation"
        ],
    )
    try:
        s16_out = advance(s16_in, live_state_path=p16)
        ok("C16 no crash",                 True)
        ok("C16 status = intervened",      s16_out["status"] == "intervened",
           "got " + s16_out["status"])
        ok("C16 approach_used in enum",    s16_out["approach_used"] in VALID_APPROACHES)
    except Exception as exc:
        ok("C16 no crash", False, str(exc))
    finally:
        if os.path.exists(p16):
            os.unlink(p16)

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
