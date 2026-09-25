from llm_client import call_llm

def generate_probes(state: dict, original_question: str) -> dict:
    """
    Input: state dict with status == "intervened"
    Output: same dict, with:
      - state["verification_probes"] = {...}
      - state["status"] becomes "verifying"
    """
    system_prompt = """You are a transfer-based mastery verification agent. Your job is NOT simply to
re-test the same question in a new format. You must distinguish TRUE conceptual
mastery from SURFACE pattern-matching (false mastery).

Given a misconception, generate exactly 3 probe questions of increasing transfer
distance:

1. "near_transfer" — same context and format as the original question, just
   different numbers/wording. Tests whether the student can repeat the corrected
   answer in a near-identical setting.

2. "far_transfer" — same underlying concept, but a different surface context
   (e.g. if the original was about pushing a box, this uses ice skaters or a
   rocket). Tests whether the concept generalizes beyond the training example.

3. "novel_context" — the concept applied in a scenario the student has not seen
   in this session at all, ideally combining it with an adjacent idea. Tests
   deep understanding rather than memorized pattern.

Return ONLY valid JSON, no markdown fences, no commentary:
{
  "probes": [
    {"level": "near_transfer", "question": "string", "options": ["a","b","c","d"],
     "correct_answer": "string"},
    {"level": "far_transfer", "question": "string", "options": ["a","b","c","d"],
     "correct_answer": "string"},
    {"level": "novel_context", "question": "string", "options": ["a","b","c","d"],
     "correct_answer": "string"}
  ]
}"""

    user_prompt = f"""Misconception: {state.get("misconception")}
Topic: {state.get("topic")}
Original question (for reference, do not repeat verbatim): {original_question}"""

    parsed_json = call_llm(system_prompt, user_prompt, primary="gemini")
    state["verification_probes"] = parsed_json
    state["status"] = "verifying"
    return state

def score_verification(state: dict, student_answers: list[str]) -> dict:
    """
    Input: state dict with status == "verifying", plus student_answers
    Output: same dict, with:
      - state["verification_result"] = string enum
      - state["status"] set to "verified" or "escalated"
      - state["flagged_false_mastery"] set to True/False
    """
    system_prompt = """Score mastery based on how far the student's correct understanding transfers.

Rules:
- All 3 correct -> "true_mastery"
- near_transfer correct, but far_transfer or novel_context wrong -> "surface_mastery"
  (the student memorized the corrected pattern but did not generalize it —
  this is FALSE MASTERY and must be flagged, not marked as resolved)
- near_transfer wrong -> "unresolved" (misconception still present)

Return ONLY valid JSON, no markdown fences, no commentary:
{
  "result": "true_mastery | surface_mastery | unresolved",
  "reasoning": "one sentence justifying the verdict from the three answers"
}"""
    
    probes = state["verification_probes"]["probes"]
    correct_0 = probes[0]["correct_answer"]
    correct_1 = probes[1]["correct_answer"]
    correct_2 = probes[2]["correct_answer"]
    
    student_0 = student_answers[0]
    student_1 = student_answers[1]
    student_2 = student_answers[2]
    
    user_prompt = f"""near_transfer: correct={correct_0}, student={student_0}
far_transfer: correct={correct_1}, student={student_1}
novel_context: correct={correct_2}, student={student_2}"""

    verdict = call_llm(system_prompt, user_prompt, primary="groq")

    result = verdict.get("result", "unresolved")
    state["verification_result"] = result
    
    if result == "true_mastery":
        state["status"] = "verified"
        state["flagged_false_mastery"] = False
    elif result == "surface_mastery":
        state["status"] = "verified"
        state["flagged_false_mastery"] = True
    else:  # unresolved
        state["status"] = "escalated"
        state["attempts"] += 1
        
    return state
