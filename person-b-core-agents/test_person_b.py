import json
import os
from loop_controller import advance, LIVE_STATE_PATH

mock_state = {
    "student_id": "s1",
    "topic": "force_concept",
    "misconception": "thinks force depends on mass alone, ignoring acceleration",
    "status": "diagnosed",
    "attempts": 1,
    "previous_approaches": [],
    "resource_given": None,
    "approach_used": None,
    "verification_probes": None,
    "verification_result": None,
    "flagged_false_mastery": False
}

mock_original_question = (
    "A 2kg box and a 5kg box are pushed with the same force. Which accelerates faster?"
)

def main():
    global mock_state
    
    print("=== Scenario 1: Surface Mastery ===")
    print("Step 1: Get recommendation...")
    mock_state = advance(mock_state)
    print("After recommend:")
    print(json.dumps(mock_state, indent=2))
    print("-" * 40)

    print("Step 2: Generate probes...")
    mock_state = advance(mock_state, original_question=mock_original_question)
    print("After generate_probes:")
    print(json.dumps(mock_state, indent=2))
    print("-" * 40)

    print("Step 3: Score verification (simulating surface mastery)...")
    mock_student_answers = [
        mock_state["verification_probes"]["probes"][0]["correct_answer"],  # gets near_transfer right
        "wrong",  # gets far_transfer wrong
        "wrong",  # gets novel_context wrong
    ]
    mock_state = advance(mock_state, student_answers=mock_student_answers)
    print("After scoring:")
    print(json.dumps(mock_state, indent=2))
    print("-" * 40)
    
    print("\n=== Scenario 2: Unresolved (escalation path) ===")
    mock_state_2 = {
        "student_id": "s2",
        "topic": "force_concept",
        "misconception": "thinks force depends on mass alone, ignoring acceleration",
        "status": "diagnosed",
        "attempts": 1,
        "previous_approaches": [],
        "resource_given": None,
        "approach_used": None,
        "verification_probes": None,
        "verification_result": None,
        "flagged_false_mastery": False
    }

    mock_state_2 = advance(mock_state_2)
    print("After recommend:")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    mock_state_2 = advance(mock_state_2, original_question="A 2kg box and a 5kg box are pushed with the same force. Which accelerates faster?")
    print("After generate_probes:")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    # Student gets near_transfer WRONG — should trigger escalation, not surface_mastery
    wrong_near_transfer_answers = ["wrong", "wrong", "wrong"]
    mock_state_2 = advance(mock_state_2, student_answers=wrong_near_transfer_answers)
    print("After scoring (expect status=escalated, attempts=2):")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    assert mock_state_2["status"] == "escalated", f"Expected 'escalated', got {mock_state_2['status']}"
    assert mock_state_2["attempts"] == 2, f"Expected attempts=2, got {mock_state_2['attempts']}"
    print("Escalation path confirmed correct")

    print("\n=== shared/live_state.json ===")
    with open(LIVE_STATE_PATH, "r") as f:
        print(f.read())

if __name__ == "__main__":
    main()
