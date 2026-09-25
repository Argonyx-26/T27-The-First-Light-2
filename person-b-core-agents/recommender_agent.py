from llm_client import call_llm

def recommend(state: dict) -> dict:
    """
    Input: state dict conforming to the contract, with status == "diagnosed" or "escalated"
    Output: same dict, with:
      - state["resource_given"] = ...
      - state["approach_used"] = ...
      - state["status"] = "intervened"
    """
    misconception = state.get("misconception")
    topic = state.get("topic")
    attempt_number = state.get("attempts", 1)
    previous_approaches = state.get("previous_approaches", [])
    
    system_prompt = """You are a recommender agent in an adaptive learning system. You receive a
diagnosed misconception and produce ONE targeted intervention that directly
addresses it — not a generic topic review.

Given:
- The misconception (specific, one sentence)
- The topic
- attempt_number (1 = first try, 2+ = previous explanation didn't work, use a
  DIFFERENT teaching approach this time — worked example, analogy, or visual
  description instead of repeating the same explanation style)

Return ONLY valid JSON, no markdown fences, no commentary:
{
  "resource_given": "a short, targeted explanation (3-5 sentences) and a practice hint that directly corrects this exact misconception",
  "approach_used": "direct_explanation | worked_example | analogy | visual_description"
}

If attempt_number > 1, you MUST use a different approach_used than any value
listed in previous_approaches."""

    user_prompt = f"""Misconception: {misconception}
Topic: {topic}
Attempt number: {attempt_number}
Previous approaches tried: {previous_approaches}"""

    parsed_json = call_llm(system_prompt, user_prompt, primary="groq")

    state["resource_given"] = parsed_json.get("resource_given")
    approach_used = parsed_json.get("approach_used")
    state["approach_used"] = approach_used
    
    if "resource" in state:
        del state["resource"]
        
    state["status"] = "intervened"
    
    if "previous_approaches" not in state:
        state["previous_approaches"] = []
    if approach_used:
        state["previous_approaches"].append(approach_used)
        
    return state
