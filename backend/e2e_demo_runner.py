import json
import os
import sys
import time

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "person-b-core-agents"))
from llm_client import call_llm

SHARED_STATE = os.path.join(os.path.dirname(__file__), "..", "shared", "live_state.json")

def load_state():
    try:
        from db_client import get_all_student_states
        res = get_all_student_states()
        if res:
            return res
    except Exception as e:
        print(f"[E2E] Supabase fetch failed: {e}. Falling back to live_state.json.")
        
    with open(SHARED_STATE, "r", encoding="utf-8-sig") as f:
        content = f.read().strip()
        return json.loads(content) if content else []

def save_state(state_list, target_student=None):
    if target_student:
        try:
            from db_client import upsert_student_state
            upsert_student_state(target_student)
        except Exception as e:
            print(f"[E2E] Supabase upsert failed: {e}")
            
    with open(SHARED_STATE, "w", encoding="utf-8") as f:
        json.dump(state_list, f, indent=2)

def run_person_a_diagnostic(student, quiz_question, student_answer):
    print(f"\n[Learning Diagnosis] Diagnosing student {student.get('student_id')}...")
    sys_prompt = "You are a Learning Diagnosis. Analyze the math answer. Return JSON: {\"topic\": \"...\", \"misconception\": \"...\"}"
    user_prompt = f"Question: {quiz_question}\nStudent Answer: {student_answer}"
    
    res = call_llm(sys_prompt, user_prompt, primary="gemini")
    
    student["topic"] = res.get("topic", "fraction_addition")
    student["misconception"] = res.get("misconception", "unknown error")
    student["status"] = "diagnosed"
    return student

def run_person_b_intervention(student):
    print(f"[Personalized Practice] Recommending intervention for {student['misconception']}...")
    sys_prompt = "You are an Intervention Agent. Choose ONE approach from ['worked_example', 'analogy', 'visual_description', 'direct_explanation'] and provide an explanation. Return JSON: {\"approach_used\": \"...\", \"resource_given\": \"...\"}"
    user_prompt = f"Topic: {student['topic']}\nMisconception: {student['misconception']}"
    
    res = call_llm(sys_prompt, user_prompt, primary="gemini")
    
    student["approach_used"] = res.get("approach_used", "analogy")
    student["resource_given"] = res.get("resource_given", "Here is a helpful explanation.")
    student["attempts"] += 1
    if student["approach_used"] not in student.get("previous_approaches", []):
        student.setdefault("previous_approaches", []).append(student["approach_used"])
    student["status"] = "intervened"
    return student

def run_person_b_verification(student, follow_up_answer):
    print(f"[Personalized Practice] Verifying transfer mastery...")
    sys_prompt = "You are a Verification Agent. Determine if the answer shows 'true_mastery', 'surface_mastery', or 'unresolved'. Return JSON: {\"verification_result\": \"...\", \"reasoning\": \"...\"}"
    user_prompt = f"Topic: {student['topic']}\nIntervention given: {student['resource_given']}\nFollow-up question answer: {follow_up_answer}"
    
    res = call_llm(sys_prompt, user_prompt, primary="gemini")
    
    v_res = res.get("verification_result", "unresolved")
    student["verification_result"] = v_res
    if v_res == "surface_mastery":
        student["flagged_false_mastery"] = True
        student["status"] = "verified"
    elif v_res == "true_mastery":
        student["status"] = "verified"
    else:
        student["status"] = "escalated"
    return student

def run_e2e_demo():
    print("==================================================")
    print(" RUNNING END-TO-END DEMO SCRIPT")
    print("==================================================")
    
    students = load_state()
    if not students:
        print(" No students found in Supabase/live_state.json. Please connect Google Classroom first!")
        return

    # Grab the first pending student
    target = next((s for s in students if s["status"] == "pending"), None)
    if not target:
        print(" All students are already processed! Reset data to run again.")
        return

    # 1. QUIZ TAKEN -> DIAGNOSED
    quiz_q = "What is 1/3 + 1/4?"
    student_a = "2/7"
    print(f" Simulated Quiz Activity for: {target.get('name')}")
    print(f" Question: {quiz_q} | Answer: {student_a}")
    target = run_person_a_diagnostic(target, quiz_q, student_a)
    save_state(students, target)
    time.sleep(1)

    # 2. INTERVENED
    target = run_person_b_intervention(target)
    save_state(students, target)
    time.sleep(1)
    
    # 3. VERIFIED (Simulate follow up answer indicating surface mastery)
    follow_up = "I multiply the top and bottom."
    target = run_person_b_verification(target, follow_up)
    save_state(students, target)
    
    print("\n End-to-End Pipeline Complete!")
    print(f"Dashboard should now show {target.get('name')} as {target['status']} with False Mastery flagged = {target['flagged_false_mastery']}.")
    print("Check the dashboard UI!")

if __name__ == '__main__':
    run_e2e_demo()
