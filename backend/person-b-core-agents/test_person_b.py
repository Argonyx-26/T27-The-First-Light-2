import json
import os
from loop_controller import advance, DEFAULT_LIVE_STATE_PATH as LIVE_STATE_PATH

def main():
    print("=== Scenario 1: Surface Mastery ===")
    mock_state = {
        "student_id": "s1",
        "topic": "force_concept",
        "misconception": "thinks force depends on mass alone, ignoring acceleration",
        "status": "diagnosed",
        "attempts": 1,
        "previous_approaches": [],
        "resource_given": None,
        "approach_used": None,
        "verification_result": "pending",
        "flagged_false_mastery": False
    }

    print("Step 1: Get recommendation...")
    mock_state = advance(mock_state)
    print("After recommend:")
    print(json.dumps(mock_state, indent=2))
    print("-" * 40)

    print("Step 2: Transition to verifying...")
    mock_state = advance(mock_state)
    print("After transition:")
    print(json.dumps(mock_state, indent=2))
    print("-" * 40)

    print("Step 3: Score verification (simulating surface mastery)...")
    mock_state = advance(mock_state)
    print("After scoring:")
    print(json.dumps(mock_state, indent=2))
    print("=" * 60)

    print("\n=== Scenario 2: Unresolved -> Escalated -> New Approach ===")
    mock_state_2 = {
        "student_id": "s2",
        "topic": "force_concept",
        "misconception": "thinks force depends on mass alone, ignoring acceleration",
        "status": "diagnosed",
        "attempts": 2,
        "previous_approaches": ["worked_example", "analogy"],
        "resource_given": None,
        "approach_used": None,
        "verification_result": "pending",
        "flagged_false_mastery": False
    }

    print("Step 1: Get recommendation (second attempt)...")
    mock_state_2 = advance(mock_state_2)
    print("After recommend:")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    print("Step 2: Transition to verifying...")
    mock_state_2 = advance(mock_state_2)
    print("After transition:")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    print("Step 3: Score verification (simulating failure)...")
    mock_state_2 = advance(mock_state_2)
    print("After scoring:")
    print(json.dumps(mock_state_2, indent=2))
    print("-" * 40)

    print("Step 4: Retry loop -> Intervened again with new approach...")
    mock_state_2 = advance(mock_state_2)
    print("After retry:")
    print(json.dumps(mock_state_2, indent=2))
    print("=" * 60)

if __name__ == "__main__":
    main()
