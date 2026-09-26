import os
import sys
import json
import logging
from typing import Dict, Any

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DiagnosticAgent")

# Setup paths for importing shared modules
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

# person-b-core-agents is currently where llm_client lives in this project structure
_PERSON_B = os.path.join(_PARENT, "person-b-core-agents")
if _PERSON_B not in sys.path:
    sys.path.insert(0, _PERSON_B)

try:
    from llm_client import call_llm
    from db_client import upsert_student_state
    _IMPORTS_OK = True
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    _IMPORTS_OK = False


def run_diagnostic(
    student_id: str,
    question: str,
    student_answer: str,
    correct_answer: str,
    topic: str
) -> Dict[str, Any]:
    """
    Run the Learning Diagnosis to analyze a student's answer and save to Supabase.
    """
    if not _IMPORTS_OK:
        logger.error("run_diagnostic called but imports failed — skipping LLM diagnosis")
        return {"student_id": student_id, "topic": topic, "status": "error", "error": "import_failure"}

    logger.info(f"Starting diagnostic for student_id={student_id}, topic={topic}")
    
    system_prompt = (
        "You are an expert educational Learning Diagnosis. Your task is to analyze a student's incorrect "
        "or incomplete answer to a question and identify their core misconception.\n\n"
        "You must output ONLY valid JSON matching this exact structure:\n"
        "{\n"
        '  "topic": "...",\n'
        '  "misconception": "...",\n'
        '  "misconception_id": "...",\n'
        '  "error_type": "conceptual_misconception | factual_gap | calculation_error | careless_error",\n'
        '  "evidence": "...",\n'
        '  "confidence": 0.0,\n'
        '  "status": "unresolved"\n'
        "}\n"
    )
    
    user_prompt = (
        f"Topic: {topic}\n"
        f"Question: {question}\n"
        f"Correct Answer: {correct_answer}\n"
        f"Student Answer: {student_answer}\n"
    )
    
    try:
        # Call the LLM to get the diagnostic JSON
        logger.info("Calling LLM for diagnosis...")
        diagnostic_result = call_llm(system_prompt, user_prompt, primary="gemini")
        logger.info(f"LLM Response received: {json.dumps(diagnostic_result)}")
        
        # Merge the generated diagnostic with the student_id for database upsert
        state_dict = diagnostic_result.copy()
        state_dict["student_id"] = student_id
        
        # Add required defaults for the student_state table if not provided by LLM
        if "attempts" not in state_dict:
            state_dict["attempts"] = 1
        if "previous_approaches" not in state_dict:
            state_dict["previous_approaches"] = []
            
        # The prompt asked for "status": "unresolved", but loop controller originally expects "diagnosed".
        # We will use what the LLM generated (or "unresolved" as a fallback).
        if "status" not in state_dict:
            state_dict["status"] = "unresolved"
            
        logger.info("Writing diagnostic result to student_state table via db_client...")
        upsert_result = upsert_student_state(state_dict)
        
        if upsert_result:
            logger.info("Successfully upserted student state to database.")
        else:
            logger.warning("Upsert returned None (could be due to missing Supabase client or DB error).")
            
        return state_dict
        
    except Exception as e:
        logger.error(f"Error during diagnostic process: {e}", exc_info=True)
        return {
            "student_id": student_id,
            "topic": topic,
            "error": str(e),
            "status": "error"
        }

if __name__ == "__main__":
    # Simple test execution if run directly
    test_result = run_diagnostic(
        student_id="123e4567-e89b-12d3-a456-426614174000", # Example UUID
        question="What is 1/3 + 1/4?",
        student_answer="2/7",
        correct_answer="7/12",
        topic="Fractions"
    )
    print("\nFinal Output:")
    print(json.dumps(test_result, indent=2))
