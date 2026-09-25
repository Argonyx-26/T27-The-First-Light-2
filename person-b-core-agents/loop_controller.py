import json
import os
from recommender_agent import recommend
from verification_agent import generate_probes, score_verification

LIVE_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "shared", "live_state.json")

def _persist_state(state: dict) -> None:
    os.makedirs(os.path.dirname(LIVE_STATE_PATH), exist_ok=True)
    if os.path.exists(LIVE_STATE_PATH):
        with open(LIVE_STATE_PATH, "r") as f:
            try:
                all_states = json.load(f)
            except json.JSONDecodeError:
                all_states = {}
    else:
        all_states = {}
        
    all_states[state["student_id"]] = state
    
    with open(LIVE_STATE_PATH, "w") as f:
        json.dump(all_states, f, indent=2)

def advance(state: dict, student_answers: list[str] | None = None,
            original_question: str | None = None) -> dict:
    """
    One step of the B-owned portion of the pipeline.
    """
    if state["status"] in ("diagnosed", "escalated"):
        state = recommend(state)
        _persist_state(state)
        return state

    if state["status"] == "intervened":
        state = generate_probes(state, original_question)
        _persist_state(state)
        return state

    if state["status"] == "verifying":
        if student_answers is None:
            raise ValueError("student_answers required when status is verifying")
        state = score_verification(state, student_answers)
        _persist_state(state)
        return state

    raise ValueError(f"loop_controller.advance called with unexpected status: {state['status']}")
